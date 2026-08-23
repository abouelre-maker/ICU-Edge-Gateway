# IMPORTANT, honest limitation: step-ca generates its own root key/cert
# INSIDE the running container at first boot (step-ca's own init process,
# triggered by STEPCA_INIT_NAME) -- Terraform has no visibility into that
# generated material and CANNOT output it as a plain "here is the PEM"
# value the way a Terraform-generated cert (e.g. via the `tls` provider)
# could. step-ca exposes its root CA certificate(s) itself, at a
# well-known, UNAUTHENTICATED endpoint by design (GET /roots.pem) --
# that's the actual mechanism for retrieving ca_certificate_pem for
# distribution (see DESIGN.md §1's k3s-Secret-population step). The output
# below is the URL to fetch it FROM, not the certificate itself.

output "step_ca_endpoint" {
  description = "Internal NLB DNS name:port for step-ca. Fetch the root CA cert via GET https://<this>/roots.pem (step-ca's own well-known, unauthenticated-by-design endpoint -- the root cert is public, non-secret data, same reasoning as the local mock's plain-HTTP CA-bundle endpoint)."
  value       = "${aws_lb.step_ca.dns_name}:9000"
}

output "ecs_cluster_name" {
  value = aws_ecs_cluster.this.name
}

output "task_security_group_id" {
  description = "Pass to modules/provisioning-api so its Lambdas' security group can be added to allowed_client_security_group_ids."
  value       = aws_security_group.step_ca_task.id
}
