output "bootstrap_url" {
  description = "Set config.PROVISIONING_BOOTSTRAP_URL (device side) to this value."
  value       = "https://${var.custom_domain_name}"
}

output "alb_dns_name" {
  description = "Point custom_domain_name's DNS record at this (Route53 alias or equivalent -- not created by this module, see DESIGN.md §4)."
  value       = aws_lb.provisioning.dns_name
}

output "enrollment_tokens_table_name" {
  description = "For the (not-yet-built, see DESIGN.md §4) admin token-issuance process to write single-use token records into."
  value       = aws_dynamodb_table.enrollment_tokens.name
}

output "device_revocations_table_name" {
  value = aws_dynamodb_table.device_revocations.name
}

output "lambda_security_group_id" {
  description = "Pass to modules/ca's allowed_client_security_group_ids so these Lambdas can reach step-ca's signing port -- note the circular-looking dependency with modules/ca's own step_ca_endpoint output: this env wiring (envs/dev/main.tf) resolves it via Terraform's normal module-output graph, not an actual cycle (ca depends on this SG id; this module depends on ca's endpoint -- both resolve because the SG resource itself doesn't need the endpoint to exist first)."
  value       = aws_security_group.lambda.id
}
