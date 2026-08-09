# =============================================================================
# ICU Edge Gateway — dev environment wiring.
# Phase 5-Stream Section C. Not applied anywhere -- no cloud account
# available in this sandbox, no `terraform` CLI to plan/validate against.
# Reviewed design only; see ../../DESIGN.md.
# =============================================================================

terraform {
  required_version = ">= 1.5"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }
}

provider "aws" {
  region = var.aws_region
}

module "ca" {
  source = "../../modules/ca"

  name_prefix         = var.name_prefix
  vpc_id              = var.vpc_id
  private_subnet_ids  = var.private_subnet_ids
  ca_name             = "ICU Edge Gateway Control-Plane CA (dev)"
  allowed_client_security_group_ids = [module.provisioning_api.lambda_security_group_id]
}

module "provisioning_api" {
  source = "../../modules/provisioning-api"

  name_prefix                        = var.name_prefix
  vpc_id                              = var.vpc_id
  private_subnet_ids                  = var.private_subnet_ids
  step_ca_endpoint                    = module.ca.step_ca_endpoint
  step_ca_task_security_group_id      = module.ca.task_security_group_id
  step_ca_provisioner_jwk_secret_arn  = var.step_ca_provisioner_jwk_secret_arn
  custom_domain_name                  = var.provisioning_domain_name
  acm_certificate_arn                 = var.provisioning_acm_certificate_arn
}

module "telemetry" {
  source = "../../modules/telemetry"

  name_prefix                        = var.name_prefix
  ca_certificate_pem                  = var.ca_root_certificate_pem
  ca_certificate_registration_config  = var.iot_ca_verification_certificate_pem
}

# =============================================================================
# MANUAL BOOTSTRAP STEPS -- deliberately NOT automated by this Terraform
# (see DESIGN.md §4 for why each is out of scope for this pass):
#
#   1. After `terraform apply` of module.ca: fetch the root cert via
#      `curl https://$(terraform output -raw ca_step_ca_endpoint)/roots.pem`
#      and set it as var.ca_root_certificate_pem, THEN apply module.telemetry.
#   2. Bootstrap step-ca's JWK provisioner (`step ca provisioner add`,
#      against the running ECS task) and store the resulting private key
#      in the Secrets Manager secret var.step_ca_provisioner_jwk_secret_arn
#      points at, BEFORE the provisioning-api Lambdas can successfully
#      sign anything.
#   3. Generate an IoT Core CA registration verification certificate
#      (AWS's proof-of-possession flow against modules/ca) and set it as
#      var.iot_ca_verification_certificate_pem.
#   4. Import a certificate ISSUED BY modules/ca into ACM (not a normal
#      public ACM cert -- see provisioning-api/variables.tf's
#      acm_certificate_arn docstring) and set var.provisioning_acm_
#      certificate_arn.
#   5. Point var.provisioning_domain_name's DNS at module.provisioning_
#      api's alb_dns_name output (Route53 alias or equivalent).
#   6. Populate deploy/k3s/edge-appliance.yaml's icu-edge-enrollment-token
#      Secret with a token issued via whatever admin process eventually
#      writes into module.provisioning_api.enrollment_tokens_table_name
#      (not built in this pass), and the CA bundle from step 1 -- SAME
#      Secret, SAME timing, per the explicit CA-bundle-distribution
#      constraint this section opened with.
# =============================================================================
