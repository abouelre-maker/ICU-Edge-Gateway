output "bootstrap_url" {
  value = module.provisioning_api.bootstrap_url
}

output "alb_dns_name_to_point_dns_at" {
  value = module.provisioning_api.alb_dns_name
}

output "step_ca_endpoint_for_roots_pem_fetch" {
  description = "Direct-to-NLB fallback -- only reachable from inside the VPC/bastion. Prefer roots_proxy_public_url below for the normal bootstrap flow."
  value       = module.ca.step_ca_endpoint
}

output "roots_proxy_public_url" {
  description = "The actual bootstrap URL for DESIGN.md §1's `curl .../roots.pem` step -- publicly reachable, GET /roots.pem only (HAZARD-STREAM-012 gap 1, DESIGN.md §4)."
  value       = module.roots_proxy.public_url
}

output "roots_proxy_alb_dns_name_to_point_dns_at" {
  value = module.roots_proxy.alb_dns_name
}

output "kinesis_stream_arn" {
  value = module.telemetry.kinesis_stream_arn
}
