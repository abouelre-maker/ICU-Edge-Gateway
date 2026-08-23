variable "name_prefix" {
  description = "Prefix for all resource names in this module (e.g. \"icu-edge-dev\")."
  type        = string
}

variable "vpc_id" {
  description = "VPC to deploy step-ca into."
  type        = string
}

variable "private_subnet_ids" {
  description = "Private subnet IDs for the ECS task and EFS mount targets. Must NOT be public -- step-ca's admin API (provisioning-api's Lambdas talk to it) has no reason to be internet-reachable."
  type        = list(string)
}

variable "step_ca_image" {
  description = "step-ca container image. Pin to a specific digest in production -- see DESIGN.md's SOUP-equivalent note; \"smallstep/step-ca:latest\" is a placeholder for initial `terraform plan` review only."
  type        = string
  default     = "smallstep/step-ca:0.27.4"
}

variable "ca_name" {
  description = "The CA's own name/CN, e.g. \"ICU Edge Gateway Control-Plane CA\"."
  type        = string
}

variable "task_cpu" {
  description = "Fargate task CPU units. 256 (0.25 vCPU) is generous for step-ca's actual load at this project's fleet scale (short-lived-cert signing is cheap); sized up only if profiling says otherwise."
  type        = number
  default     = 256
}

variable "task_memory" {
  description = "Fargate task memory (MiB)."
  type        = number
  default     = 512
}

variable "allowed_client_security_group_ids" {
  description = "Security groups (e.g. provisioning-api's Lambda SG) permitted to reach step-ca's port. step-ca terminates its own TLS -- this module does not add a second TLS layer in front of it."
  type        = list(string)
}
