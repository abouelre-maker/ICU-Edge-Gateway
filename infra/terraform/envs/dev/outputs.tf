output "bootstrap_url" {
  value = module.provisioning_api.bootstrap_url
}

output "alb_dns_name_to_point_dns_at" {
  value = module.provisioning_api.alb_dns_name
}

output "step_ca_endpoint_for_roots_pem_fetch" {
  value = module.ca.step_ca_endpoint
}

output "kinesis_stream_arn" {
  value = module.telemetry.kinesis_stream_arn
}
