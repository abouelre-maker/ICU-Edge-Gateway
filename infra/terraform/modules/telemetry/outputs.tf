output "kinesis_stream_name" {
  value = aws_kinesis_stream.telemetry.name
}

output "kinesis_stream_arn" {
  value = aws_kinesis_stream.telemetry.arn
}

output "iot_policy_name" {
  value = aws_iot_policy.device_telemetry.name
}
