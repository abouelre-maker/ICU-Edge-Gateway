variable "aws_region" {
  type    = string
  default = "us-east-1"
}

variable "name_prefix" {
  type    = string
  default = "icu-edge-dev"
}

variable "vpc_id" {
  type = string
}

variable "private_subnet_ids" {
  type = list(string)
}

variable "step_ca_provisioner_jwk_secret_arn" {
  description = "See main.tf's MANUAL BOOTSTRAP STEPS #2."
  type        = string
}

variable "provisioning_domain_name" {
  description = "Must match config.PROVISIONING_BOOTSTRAP_URL on the device side exactly."
  type        = string
}

variable "provisioning_acm_certificate_arn" {
  description = "See main.tf's MANUAL BOOTSTRAP STEPS #4."
  type        = string
}

variable "ca_root_certificate_pem" {
  description = "See main.tf's MANUAL BOOTSTRAP STEPS #1."
  type        = string
}

variable "iot_ca_verification_certificate_pem" {
  description = "See main.tf's MANUAL BOOTSTRAP STEPS #3."
  type        = string
}
