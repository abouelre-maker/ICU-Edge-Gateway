# =============================================================================
# ICU Edge Gateway — Telemetry Ingestion (AWS IoT Core + Kinesis)
# Phase 5-Stream Section C. See ../../DESIGN.md §3 for why AWS IoT Core was
# chosen over Azure IoT Hub / GCP Pub/Sub.
#
# Registers modules/ca's CA with IoT Core so devices authenticate their
# MQTT telemetry connections with the SAME certificate reattestation_
# loop()/mqtt_publisher.py already hold -- no second enrollment flow, no
# second trust chain.
# =============================================================================

# CAVEAT (honest, not silently glossed over): this sandbox has no
# `terraform` CLI to run `terraform validate`/`plan` against, so the exact
# argument names below for aws_iot_ca_certificate are written from
# specification recall, not confirmed against the live hashicorp/aws
# provider schema at whatever version this is applied with -- verify
# ca_certificate_pem/certificate_pem/registration_config's exact shape
# against the provider docs for the pinned aws provider version before
# `terraform apply`, same as any other unreviewed infra code.
resource "aws_iot_ca_certificate" "device_ca" {
  active                   = true
  ca_certificate_pem       = var.ca_certificate_pem
  certificate_pem          = var.ca_certificate_registration_config
  registration_config {
    template_body = jsonencode({
      Parameters = {},
      Resources = {
        thing = {
          Type = "AWS::IoT::Thing"
          Properties = {
            ThingName = { Ref = "AWS::IoT::Certificate::CommonName" }
          }
        }
        certificate = {
          Type = "AWS::IoT::Certificate"
          Properties = {
            CertificateId = { Ref = "AWS::IoT::Certificate::Id" }
            Status        = "ACTIVE"
          }
        }
        policy = {
          Type = "AWS::IoT::Policy"
          Properties = {
            PolicyName = aws_iot_policy.device_telemetry.name
          }
        }
      }
    })
  }
  allow_auto_registration = true
}

# Policy scoped to EXACTLY the topic pattern mqtt_publisher.py already
# publishes to (config.get_mqtt_config().topic_prefix, per-device) -- a
# device's certificate (bound to its own common_name / Thing name) can
# only publish to ITS OWN topic, not any other device's, so a compromised
# single device cannot inject telemetry claiming to be a different one.
resource "aws_iot_policy" "device_telemetry" {
  name = "${var.name_prefix}-device-telemetry"

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect   = "Allow"
        Action   = "iot:Connect"
        Resource = "arn:aws:iot:*:*:client/$${iot:Connection.Thing.ThingName}"
      },
      {
        Effect = "Allow"
        Action = "iot:Publish"
        Resource = [
          # Matches mqtt_publisher.py's topic_prefix convention --
          # per-device topic, keyed by the device's OWN Thing name
          # (derived from its cert's common_name, which IS
          # config.get_device_common_name() -- see modules/ca's role in
          # that identity chain).
          "arn:aws:iot:*:*:topic/icu-edge/$${iot:Connection.Thing.ThingName}/*"
        ]
      },
    ]
  })
}

resource "aws_kinesis_stream" "telemetry" {
  name             = "${var.name_prefix}-telemetry"
  shard_count      = var.kinesis_shard_count
  retention_period = 24 # hours -- durable buffer for downstream consumers, not permanent storage

  encryption_type = "KMS"
  kms_key_id      = "alias/aws/kinesis"

  tags = {
    Component = "telemetry-ingestion"
  }
}

resource "aws_iam_role" "iot_rule" {
  name_prefix        = "${var.name_prefix}-iot-rule-"
  assume_role_policy = data.aws_iam_policy_document.iot_assume_role.json
}

data "aws_iam_policy_document" "iot_assume_role" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["iot.amazonaws.com"]
    }
  }
}

resource "aws_iam_role_policy" "iot_rule_kinesis" {
  name_prefix = "${var.name_prefix}-iot-rule-kinesis-"
  role        = aws_iam_role.iot_rule.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect   = "Allow"
        Action   = "kinesis:PutRecord"
        Resource = aws_kinesis_stream.telemetry.arn
      }
    ]
  })
}

resource "aws_iot_topic_rule" "telemetry_to_kinesis" {
  name        = "${replace(var.name_prefix, "-", "_")}_telemetry_to_kinesis"
  enabled     = true
  sql         = "SELECT * FROM 'icu-edge/+/telemetry'" # matches mqtt_publisher.py's topic shape
  sql_version = "2016-03-23"

  kinesis {
    stream_name   = aws_kinesis_stream.telemetry.name
    role_arn      = aws_iam_role.iot_rule.arn
    partition_key = "$${topic(2)}" # partitions by device -- the Thing name segment of the topic
  }
}
