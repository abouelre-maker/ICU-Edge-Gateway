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

  name_prefix        = var.name_prefix
  vpc_id             = var.vpc_id
  private_subnet_ids = var.private_subnet_ids
  ca_name            = "ICU Edge Gateway Control-Plane CA (dev)"
  # roots_proxy's Lambda gets the SAME trust level provisioning_api's
  # Lambdas already have (allow-listed into step-ca's port) -- not a new
  # or broader one. See modules/roots-proxy/main.tf's header for why a
  # narrow public proxy Lambda, rather than any change to this NLB/SG
  # itself, is how HAZARD-STREAM-012 gap 1 (DESIGN.md §4) is addressed.
  allowed_client_security_group_ids = [
    module.provisioning_api.lambda_security_group_id,
    module.roots_proxy.lambda_security_group_id,
  ]
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

# Narrow public route for GET /roots.pem ONLY -- see modules/roots-proxy/
# main.tf's header for the full reasoning (resolves HAZARD-STREAM-012 gap
# 1, DESIGN.md §4). step-ca's own NLB/security group above are untouched.
module "roots_proxy" {
  source = "../../modules/roots-proxy"

  name_prefix                    = var.name_prefix
  vpc_id                          = var.vpc_id
  private_subnet_ids              = var.private_subnet_ids
  step_ca_endpoint                = module.ca.step_ca_endpoint
  step_ca_task_security_group_id  = module.ca.task_security_group_id
  custom_domain_name              = var.roots_proxy_domain_name
  acm_certificate_arn             = var.roots_proxy_acm_certificate_arn
}

# =============================================================================
# MANUAL BOOTSTRAP STEPS -- deliberately NOT automated by this Terraform
# (see DESIGN.md §4 for why each is out of scope for this pass):
#
#   1. After `terraform apply` of module.ca AND module.roots_proxy: fetch
#      the root cert via `curl https://<roots_proxy_domain_name>/roots.pem`
#      (module.roots_proxy.public_url) and set it as
#      var.ca_root_certificate_pem, THEN apply module.telemetry. This
#      replaces the earlier (unreachable without VPN/bastion --
#      HAZARD-STREAM-012 gap 1, DESIGN.md §4) direct-to-NLB curl; an
#      operator without VPN access into this VPC can still fall back to
#      `curl https://$(terraform output -raw step_ca_endpoint_for_roots_pem_fetch)/roots.pem`
#      from inside the VPC/bastion if ever needed.
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
#   7. Get a normal publicly-trusted ACM certificate (DNS validation)
#      for var.roots_proxy_domain_name and set it as
#      var.roots_proxy_acm_certificate_arn -- see modules/roots-proxy/
#      variables.tf's acm_certificate_arn docstring for why this one does
#      NOT need to be CA-issued the way provisioning_acm_certificate_arn
#      (step 4) does.
#   8. Point var.roots_proxy_domain_name's DNS at
#      module.roots_proxy.alb_dns_name (Route53 alias or equivalent).
#   9. MANUAL VERIFICATION -- proving the ACME/admin/signing surface
#      stays exactly as unreachable through this new public route as it
#      was before module.roots_proxy existed (see DESIGN.md §4 for the
#      full rationale, repeated here as the actual runbook):
#        a. `curl -i https://<roots_proxy_domain_name>/roots.pem`
#           -> expect 200, body is a PEM certificate.
#        b. `curl -i -X POST https://<roots_proxy_domain_name>/roots.pem`
#           -> expect 403 (ALB default_action; wrong method never reaches
#           the Lambda -- see modules/roots-proxy/main.tf's listener rule).
#        c. `curl -i https://<roots_proxy_domain_name>/1.0/sign` and
#           `curl -i https://<roots_proxy_domain_name>/1.0/provisioners`
#           (step-ca's actual ACME/admin paths) -> expect 403 from the
#           SAME ALB default_action; these paths were never given a
#           listener rule, so nothing routes them to the Lambda at all.
#        d. From OUTSIDE the VPC (no VPN/bastion), confirm
#           `curl https://<module.ca.step_ca_endpoint's DNS name>:9000/...`
#           times out / fails to connect -- module.ca's NLB is still
#           internal-only, unchanged by this module.
#        e. Confirm modules/ca/variables.tf's
#           allowed_client_security_group_ids (rendered in the applied
#           plan/state) contains only module.provisioning_api's and
#           module.roots_proxy's Lambda security groups -- no broader
#           ingress was added to step-ca's own security group.
# =============================================================================
