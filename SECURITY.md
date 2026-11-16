# Security Policy

This repository is research software and is not intended to be deployed in a clinical
network. Even so, security reports are taken seriously, because the code demonstrates
patterns (device enrollment, mTLS, FHIR subscriptions) that others may reuse.

## Reporting a vulnerability

Please do **not** open a public issue for a security vulnerability. Instead, use GitHub's
private vulnerability reporting: open the repository's **Security** tab and choose
**Report a vulnerability**.

Please include the affected file or endpoint, steps to reproduce, and the impact you
expect. You can expect an acknowledgement within 14 days.

## Scope

In scope: the gateway source code in `src/`, the container image definition, and the
infrastructure templates in `infra/` and `deploy/`.

Out of scope: the local demonstration stack (`docker-compose.yml`, `demo/`), which
intentionally runs without authentication or TLS and must only be used on a local machine.
