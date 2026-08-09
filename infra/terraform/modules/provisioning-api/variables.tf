variable "name_prefix" {
  type = string
}

variable "step_ca_endpoint" {
  description = "From modules/ca's step_ca_endpoint output."
  type        = string
}

variable "step_ca_task_security_group_id" {
  description = "From modules/ca's task_security_group_id output -- this module's Lambda SG is added as an allowed client of it (see modules/ca's allowed_client_security_group_ids)."
  type        = string
}

variable "step_ca_provisioner_jwk_secret_arn" {
  description = "Secrets Manager ARN holding the step-ca provisioner's private JWK, used to sign one-time-tokens (OTT) for POST /1.0/sign calls to step-ca. NOT created by this module -- provisioning that key is a separate, deliberately-manual bootstrap step (see DESIGN.md §4), not something Terraform should generate and hold plaintext."
  type        = string
}

variable "vpc_id" {
  type = string
}

variable "private_subnet_ids" {
  type = list(string)
}

variable "custom_domain_name" {
  description = "e.g. \"control-plane.example.org\" -- must match config.get_provisioning_bootstrap_url()'s configured hostname on the device side exactly (and PROVISIONING_CA_BUNDLE_PATH's expected_hostname pin, if wired -- see enrollment_client.py's HAZARD-STREAM-010 update)."
  type        = string
}

variable "acm_certificate_arn" {
  description = <<-EOT
    ACM certificate ARN for custom_domain_name's SERVER TLS identity (the
    API's own front-door HTTPS cert, presented to devices during /enroll's
    TLS handshake).

    IMPORTANT -- this MUST be a certificate issued by modules/ca (the SAME
    private CA that issues device certs), imported into ACM via
    `aws_acm_certificate` with certificate_body/private_key/
    certificate_chain (ACM's "import" flow), NOT a normal ACM-issued
    public-CA certificate. Reasoning: PROVISIONING_CA_BUNDLE_PATH pins the
    device's TLS trust to modules/ca specifically (HAZARD-STREAM-010's
    server-authentication mitigation) -- if this API's own front-door cert
    instead chained to a public CA, that pin would have nothing meaningful
    to validate against and the mitigation would be defeated at exactly
    the point it's supposed to matter. This exactly mirrors deploy/local's
    mock control plane, which deliberately signs its own HTTPS leaf cert
    with the SAME CA it uses to issue device certs (see generate_certs.py's
    docstring) -- this module keeps that property in the real deployment,
    not just the local mock.
  EOT
  type        = string
}
