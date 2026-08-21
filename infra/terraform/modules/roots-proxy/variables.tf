variable "name_prefix" {
  type = string
}

variable "vpc_id" {
  type = string
}

variable "private_subnet_ids" {
  description = "NAT-routed public-facing subnets in a real VPC layout (named private_subnet_ids to match the other modules' variable -- see modules/provisioning-api/main.tf's identical note)."
  type        = list(string)
}

variable "step_ca_endpoint" {
  description = "From modules/ca's step_ca_endpoint output. This module's Lambda fetches GET https://<this>/roots.pem over the internal NLB -- same endpoint, same mechanism modules/provisioning-api's reattest.py Lambda already uses to load the CA root."
  type        = string
}

variable "step_ca_task_security_group_id" {
  description = "From modules/ca's task_security_group_id output. NOT used to create an ingress rule in THIS module -- see this module's outputs.tf's lambda_security_group_id: the env wiring (envs/dev/main.tf) is what adds that SG to modules/ca's allowed_client_security_group_ids, mirroring exactly how modules/provisioning-api's Lambda SG is already added there. This variable exists only so the dependency is explicit/documented at the call site, matching modules/provisioning-api's variables.tf convention."
  type        = string
}

variable "custom_domain_name" {
  description = "e.g. \"roots.control-plane.example.org\". A public ALB HTTPS listener needs a cert bound to a domain the operator controls -- the ALB's own AWS-assigned DNS name cannot get an ACM cert issued against it. Distinct from modules/provisioning-api's custom_domain_name (this is a read-only, unauthenticated, public endpoint -- no reason to share a hostname with the bearer-token/mTLS provisioning API)."
  type        = string
}

variable "acm_certificate_arn" {
  description = <<-EOT
    ACM certificate ARN for custom_domain_name's server TLS identity.

    UNLIKE modules/provisioning-api's acm_certificate_arn, this does NOT
    need to be a certificate issued by modules/ca -- the content served
    here (step-ca's own root cert) is already public, non-secret data by
    step-ca's own design (see modules/ca/outputs.tf's comment), and
    nothing pins its TLS identity to modules/ca the way
    PROVISIONING_CA_BUNDLE_PATH does for the provisioning API. A normal
    publicly-trusted ACM certificate (DNS- or email-validated) is
    appropriate and simpler here.
  EOT
  type = string
}
