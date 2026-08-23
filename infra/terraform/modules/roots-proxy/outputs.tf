output "alb_dns_name" {
  description = "Point custom_domain_name's DNS record at this (Route53 alias or equivalent -- not created by this module, see DESIGN.md §4)."
  value       = aws_lb.roots_proxy.dns_name
}

output "public_url" {
  description = "The actual bootstrap URL to hand to an operator in place of DESIGN.md §1's direct-to-NLB curl."
  value       = "https://${var.custom_domain_name}/roots.pem"
}

output "lambda_security_group_id" {
  description = "Pass to modules/ca's allowed_client_security_group_ids so this Lambda can reach step-ca's port over the internal NLB -- same non-cycle resolution as modules/provisioning-api's identical output (see its outputs.tf's note): modules/ca depends on this SG id, this module depends on modules/ca's step_ca_endpoint, and both resolve because the SG resource itself doesn't need the endpoint to exist first."
  value       = aws_security_group.lambda.id
}
