# =============================================================================
# ICU Edge Gateway — Provisioning API (bootstrap/enroll/reattest)
# Phase 5-Stream Section C.
#
# Implements the SERVER side of the contract enrollment_client.py already
# codifies: POST {bootstrap_url}/enroll (bearer token) and POST
# {bootstrap_url}/reattest (mTLS) -- SAME hostname for both, exactly
# matching the device-side code (both routes are built from one
# self._bootstrap_url in enrollment_client.py; the device contract was
# NOT redesigned to use two hostnames).
#
# WHY ALB, NOT API GATEWAY: one hostname serving BOTH a bearer-token route
# (/enroll -- device has no certificate yet, by construction, before its
# first successful enrollment) AND an mTLS route (/reattest -- device
# presents its already-issued cert) cannot be built on API Gateway's
# native custom-domain mTLS, because that feature is all-or-nothing PER
# DOMAIN, not per route -- enabling it would also demand a client cert on
# /enroll, which is impossible by construction. ALB's mTLS has a
# "Passthrough" mode that does NOT reject connections lacking a client
# cert -- it forwards whatever cert (if any) was presented as a header
# (x-amzn-mtls-clientcert-leaf) and leaves verification to the target.
# That is exactly the shape this needs: /enroll's Lambda ignores the
# header (bearer-token auth only); /reattest's Lambda REQUIRES the header
# to be present and verifies the forwarded cert itself (against
# modules/ca's root, fetched from step-ca's /roots.pem) rather than
# relying on the load balancer to have verified it.
# =============================================================================

# ── Token state (single-use enforcement, genuinely enforced) ────────────────
resource "aws_dynamodb_table" "enrollment_tokens" {
  name         = "${var.name_prefix}-enrollment-tokens"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "token_id"

  attribute {
    name = "token_id"
    type = "S"
  }

  # TTL on tokens -- short-lived by design (see enrollment_client.py's
  # HAZARD-STREAM-010 discussion of single-use, short-TTL tokens). Items
  # carry their own "expires_at" (epoch seconds) attribute, set by
  # whatever admin process issues a token (not built in this pass -- see
  # DESIGN.md §4).
  ttl {
    attribute_name = "expires_at"
    enabled        = true
  }

  point_in_time_recovery {
    enabled = true
  }

  server_side_encryption {
    enabled = true
  }
}

# device_id -> revocation status. reattest's Lambda checks this.
resource "aws_dynamodb_table" "device_revocations" {
  name         = "${var.name_prefix}-device-revocations"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "device_common_name"

  attribute {
    name = "device_common_name"
    type = "S"
  }

  server_side_encryption {
    enabled = true
  }
}

# ── Lambdas ───────────────────────────────────────────────────────────────
data "archive_file" "enroll" {
  type        = "zip"
  source_file = "${path.module}/lambda_src/enroll.py"
  output_path = "${path.module}/.build/enroll.zip"
}

data "archive_file" "reattest" {
  type        = "zip"
  source_file = "${path.module}/lambda_src/reattest.py"
  output_path = "${path.module}/.build/reattest.zip"
}

resource "aws_iam_role" "lambda_exec" {
  name_prefix        = "${var.name_prefix}-provisioning-lambda-"
  assume_role_policy = data.aws_iam_policy_document.lambda_assume_role.json
}

data "aws_iam_policy_document" "lambda_assume_role" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["lambda.amazonaws.com"]
    }
  }
}

resource "aws_iam_role_policy_attachment" "lambda_vpc_access" {
  role       = aws_iam_role.lambda_exec.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaVPCAccessExecutionRole"
}

resource "aws_iam_role_policy" "lambda_dynamodb" {
  name_prefix = "${var.name_prefix}-provisioning-lambda-ddb-"
  role        = aws_iam_role.lambda_exec.id
  policy      = data.aws_iam_policy_document.lambda_dynamodb.json
}

data "aws_iam_policy_document" "lambda_dynamodb" {
  statement {
    actions = [
      "dynamodb:GetItem",
      "dynamodb:PutItem",
      "dynamodb:UpdateItem", # UpdateItem with ConditionExpression -- the actual single-use enforcement, see enroll.py
    ]
    resources = [
      aws_dynamodb_table.enrollment_tokens.arn,
      aws_dynamodb_table.device_revocations.arn,
    ]
  }
}

resource "aws_iam_role_policy" "lambda_secrets" {
  name_prefix = "${var.name_prefix}-provisioning-lambda-secrets-"
  role        = aws_iam_role.lambda_exec.id
  policy      = data.aws_iam_policy_document.lambda_secrets.json
}

data "aws_iam_policy_document" "lambda_secrets" {
  statement {
    actions   = ["secretsmanager:GetSecretValue"]
    resources = [var.step_ca_provisioner_jwk_secret_arn]
  }
}

resource "aws_security_group" "lambda" {
  name_prefix = "${var.name_prefix}-provisioning-lambda-"
  vpc_id      = var.vpc_id

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
}

resource "aws_lambda_function" "enroll" {
  function_name    = "${var.name_prefix}-provisioning-enroll"
  role             = aws_iam_role.lambda_exec.arn
  handler          = "enroll.handler"
  runtime          = "python3.12"
  timeout          = 15 # matches enrollment_client.py's own _DEFAULT_REQUEST_TIMEOUT_SECONDS
  filename         = data.archive_file.enroll.output_path
  source_code_hash = data.archive_file.enroll.output_base64sha256

  vpc_config {
    subnet_ids         = var.private_subnet_ids
    security_group_ids = [aws_security_group.lambda.id]
  }

  environment {
    variables = {
      TOKENS_TABLE                  = aws_dynamodb_table.enrollment_tokens.name
      STEP_CA_ENDPOINT              = var.step_ca_endpoint
      STEP_CA_PROVISIONER_JWK_ARN   = var.step_ca_provisioner_jwk_secret_arn
    }
  }
}

resource "aws_lambda_function" "reattest" {
  function_name    = "${var.name_prefix}-provisioning-reattest"
  role             = aws_iam_role.lambda_exec.arn
  handler          = "reattest.handler"
  runtime          = "python3.12"
  timeout          = 15
  filename         = data.archive_file.reattest.output_path
  source_code_hash = data.archive_file.reattest.output_base64sha256

  vpc_config {
    subnet_ids         = var.private_subnet_ids
    security_group_ids = [aws_security_group.lambda.id]
  }

  environment {
    variables = {
      REVOCATIONS_TABLE = aws_dynamodb_table.device_revocations.name
      STEP_CA_ENDPOINT  = var.step_ca_endpoint # fetches /roots.pem to verify the forwarded client cert chain
    }
  }
}

resource "aws_lambda_permission" "enroll_alb" {
  statement_id  = "AllowALBInvoke"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.enroll.function_name
  principal     = "elasticloadbalancing.amazonaws.com"
  source_arn    = aws_lb_target_group.enroll.arn
}

resource "aws_lambda_permission" "reattest_alb" {
  statement_id  = "AllowALBInvoke"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.reattest.function_name
  principal     = "elasticloadbalancing.amazonaws.com"
  source_arn    = aws_lb_target_group.reattest.arn
}

# ── ALB: one hostname, mTLS Passthrough (see header note), path routing ────
resource "aws_security_group" "alb" {
  name_prefix = "${var.name_prefix}-provisioning-alb-"
  vpc_id      = var.vpc_id

  ingress {
    description = "Devices reach the provisioning API over the public internet -- this IS the internet-facing bootstrap endpoint (PROVISIONING_BOOTSTRAP_URL), unlike modules/ca's internal-only NLB."
    from_port   = 443
    to_port     = 443
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
}

resource "aws_lb" "provisioning" {
  name               = "${var.name_prefix}-provisioning"
  internal           = false
  load_balancer_type = "application"
  subnets            = var.private_subnet_ids # NAT-routed public-facing subnets in a real VPC layout; named private_subnet_ids here to match the other modules' variable, see README note if this needs to differ
  security_groups    = [aws_security_group.alb.id]

  # mTLS "Passthrough" mode -- devices without a client cert (enroll) are
  # NOT rejected at this layer; devices WITH one (reattest) have it
  # forwarded as a header for the target Lambda to verify itself. See
  # header note for why this mode (not "Verify") is required here.
  mutual_authentication {
    mode = "passthrough"
  }
}

resource "aws_lb_target_group" "enroll" {
  name        = "${var.name_prefix}-enroll"
  target_type = "lambda"
}

resource "aws_lb_target_group" "reattest" {
  name        = "${var.name_prefix}-reattest"
  target_type = "lambda"
}

resource "aws_lb_target_group_attachment" "enroll" {
  target_group_arn = aws_lb_target_group.enroll.arn
  target_id        = aws_lambda_function.enroll.arn
  depends_on        = [aws_lambda_permission.enroll_alb]
}

resource "aws_lb_target_group_attachment" "reattest" {
  target_group_arn = aws_lb_target_group.reattest.arn
  target_id        = aws_lambda_function.reattest.arn
  depends_on        = [aws_lambda_permission.reattest_alb]
}

resource "aws_lb_listener" "https" {
  load_balancer_arn = aws_lb.provisioning.arn
  port              = 443
  protocol          = "HTTPS"
  ssl_policy        = "ELBSecurityPolicy-TLS13-1-2-2021-06"
  # See variables.tf's acm_certificate_arn docstring -- MUST be a cert
  # imported from modules/ca, not a normal public ACM cert, for
  # PROVISIONING_CA_BUNDLE_PATH pinning to mean anything.
  certificate_arn = var.acm_certificate_arn

  default_action {
    type = "fixed-response"
    fixed_response {
      status_code  = "404"
      content_type = "text/plain"
      message_body = "not found"
    }
  }
}

resource "aws_lb_listener_rule" "enroll" {
  listener_arn = aws_lb_listener.https.arn
  priority     = 10

  action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.enroll.arn
  }

  condition {
    path_pattern {
      values = ["/enroll"]
    }
  }
}

resource "aws_lb_listener_rule" "reattest" {
  listener_arn = aws_lb_listener.https.arn
  priority     = 20

  action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.reattest.arn
  }

  condition {
    path_pattern {
      values = ["/reattest"]
    }
  }
}
