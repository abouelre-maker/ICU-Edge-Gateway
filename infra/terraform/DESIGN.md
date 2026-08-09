# ICU Edge Gateway — Cloud Control Plane: Design Notes

Phase 5-Stream Section C. This directory implements the SERVER side of the
protocol `infrastructure/provisioning/enrollment_client.py` (device side,
already shipped) codifies as a contract. Nothing here has been applied —
no cloud account is available in this sandbox; `terraform validate`/`plan`
could not be run either (no `terraform` CLI in this environment). Treat
this as a reviewed, not-yet-executed design.

## 1. CA bundle distribution — restated at the infrastructure level

**Explicit constraint (confirmed by project owner, restated here so this
module's own design notes carry it, not just the k3s manifest):**
`PROVISIONING_CA_BUNDLE_PATH`'s certificate must reach a device through
the SAME out-of-band channel and the SAME mechanism as the enrollment
token — see `deploy/k3s/edge-appliance.yaml`'s `icu-edge-enrollment-token`
Secret, which now carries both `token` and `ca_bundle.pem` keys,
provisioned atomically.

This module's role in that chain: `modules/ca`'s output `step_ca_endpoint`
(fetch `GET https://<endpoint>/roots.pem` -- step-ca's own well-known,
unauthenticated-by-design root-cert endpoint; Terraform cannot output the
PEM directly since step-ca generates its root key/cert itself inside the
running container, not via Terraform -- see `modules/ca/outputs.tf`'s
comment) is where the value for that Secret's `ca_bundle.pem` key comes
from, and
`modules/provisioning-api`'s issued enrollment tokens (via whatever
operator/fleet-management process calls it — not implemented in this pass,
see §5) are the value that belongs in that Secret's `token` key. **This
Terraform does NOT itself populate the k3s Secret** — that would require
this Terraform to have credentials into every edge cluster it doesn't own
or manage (out of scope, and a bigger blast-radius than a provisioning
system should have). What it DOES do: expose both values as Terraform
outputs (`ca_certificate_pem`, and per-device tokens issued via the
provisioning API's own admin path) so whatever fleet-provisioning process
populates the Secret — a human running `kubectl create secret`, or a
future provisioning controller — pulls both from this one source, at the
same time, rather than the CA bundle and the token having two different,
driftable origins. That "same origin, same timing, human or controller in
the loop" property is what actually satisfies the constraint; a fully
automated Terraform-to-k3s-Secret pipeline was NOT built in this pass and
would need its own explicit review (it would mean this Terraform holding
credentials to write Secrets into customer/site clusters).

## 2. Private CA — options considered

| Option | Cost (rough, monthly) | Ops burden | Fit |
|---|---|---|---|
| **A. step-ca (Smallstep), Terraform-managed, self-hosted** — chosen | ECS Fargate task + EFS: ~$15-40/mo at this scale | Moderate — you own patching/backups of one small service | Open-source, purpose-built for exactly this (short-lived cert issuance to many low-trust clients via ACME/CSR), no per-certificate fee, full control over CA policy (cert lifetime, extensions) |
| B. AWS Private CA (ACM PCA) | ~$400/mo per CA + ~$0.75-$0.001/cert depending on tier | Low — fully managed | Enterprise-grade, deep AWS IAM integration, but the flat monthly fee alone is disproportionate to a fleet of edge ICU appliances (tens-to-low-hundreds of devices, not tens of thousands) unless the org already runs ACM PCA for other purposes |
| C. HashiCorp Vault PKI secrets engine | Vault Cloud from ~$50/mo, or free if self-hosted Vault already exists | Moderate-high if standing up Vault from scratch; low if it already exists | Excellent fit IF the org already operates Vault (dynamic short-lived certs are Vault PKI's core use case); not justified to introduce Vault for this alone |

**Chosen: Option A (step-ca).** Reasoning, stated explicitly per the
"don't default silently to the most expensive option" instruction: ACM PCA
(B) is the most capable and lowest-ops option, but its flat per-CA monthly
fee is the wrong shape for this project's scale — a small/mid fleet of
edge ICU appliances issuing short-lived certs doesn't need (or benefit
from) AWS's enterprise CA-hierarchy features, and the fee would dominate
this system's entire cloud cost. Vault (C) is the right answer only if
Vault is already part of the org's infrastructure; introducing it solely
for this would be a second system to operate for no benefit over step-ca.
step-ca is open-source, was built specifically for ACME/CSR-based
short-lived-certificate issuance to many low-trust clients (exactly this
project's shape), costs roughly one small compute instance, and gives full
control over certificate policy — the tradeoff is that the team owns its
operational burden (patching, backup of the CA key, HA if that's ever
needed) instead of AWS owning it. Revisit toward B if the fleet grows by
an order of magnitude and dedicated CA-ops time becomes the bottleneck, or
toward C if Vault gets adopted for other reasons first.

See `modules/ca/` — ECS Fargate task running `smallstep/step-ca`, backed by
an EFS volume for the CA's persistent key/DB state (survives task
restarts/redeployments), NLB in front for TCP passthrough (step-ca
terminates its own TLS — the CA's private key must never be handled by
anything other than step-ca itself).

## 3. Telemetry ingestion — options considered

Cost column added retroactively to match §2's rigor -- the first pass of
this table had qualitative "fit" notes only, no dollar figures, which was
an inconsistency in how thoroughly the two decisions were justified.
Figures are rough, small/mid-fleet-scale estimates (order of ~100 devices,
minute-interval telemetry), not a quote -- re-estimate before committing
real budget.

| Option | Cost (rough, monthly) | Device-identity fit | Notes |
|---|---|---|---|
| **A. AWS IoT Core + Kinesis Data Streams** — chosen | IoT Core connectivity ~$0.08/million-minutes + Kinesis 1 shard ~$11/mo + PUT payload units ~$1-2/mo at this volume: **~$15-25/mo** | Strong — IoT Core supports **registering your own CA** ("bring your own CA" / JITR) for X.509 device authentication, so devices authenticate with the SAME cert this project's own CA (step-ca, above) already issues them. No second trust chain. | IoT Core rule routes matching MQTT topics into Kinesis for durable, ordered downstream processing. This reuses the existing device-side `mqtt_publisher.py` unmodified — it already speaks MQTT+mTLS. |
| B. Azure IoT Hub | Standard S1 tier (cheapest tier with device-management/DPS features this design needs): **~$25/mo** flat, scales in ~$25/mo units per additional 400k msgs/day | Comparable — IoT Hub's DPS (Device Provisioning Service) also supports X.509 CA-based device auth with a customer-owned root/intermediate CA. | Legitimate alternative if the org's cloud is already Azure. Not chosen here only because there's no existing Azure signal in this project; the technical fit is genuinely close to option A. |
| C. GCP Pub/Sub (+ hand-built device auth) | Pub/Sub itself is near-negligible at this volume (~$1-5/mo), but a Cloud Run/Function service to verify device-signed JWTs in front of it adds **~$5-15/mo compute, PLUS the engineering cost of building and maintaining that auth layer** — not reflected in the dollar figure | Weak, as a *device-identity* layer specifically | Pub/Sub itself is a generic message bus with no built-in device-certificate authentication. The natural pairing would have been **Google Cloud IoT Core**, which Google retired in August 2023 — there is no current GCP-native equivalent to AWS IoT Core / Azure IoT Hub's device-management + X.509 CA auth layer. Using Pub/Sub alone would require hand-building device authentication (e.g. short-lived JWTs signed by the device cert, verified by a Cloud Run/Function in front of Pub/Sub) — meaningfully more custom work than A or B for the same outcome, and that extra engineering/ops cost is the real reason this option ranks last, not the raw messaging price, which is actually the cheapest of the three. |

**Chosen: Option A (AWS IoT Core + Kinesis).** Primary reason: IoT Core's
own-CA registration means the SAME certificate `reattestation_loop()`/
`mqtt_publisher.py` already use for mTLS becomes the device's telemetry
credential too — no second enrollment flow, no second cert. Kinesis
downstream gives durable, ordered, replayable ingestion without building
a queue. Picking AWS for telemetry also keeps this design on one cloud
alongside `modules/ca` and `modules/provisioning-api`, which is simpler to
operate than spanning providers without a specific reason to.

See `modules/telemetry/` — `aws_iot_ca_certificate` (registers step-ca's
CA cert with IoT Core), an IoT policy scoped to per-device MQTT topics
(`icu-edge/{device_common_name}/telemetry`, matching the topic-prefix
convention `mqtt_publisher.py` already uses), an `aws_iot_topic_rule`
routing that topic pattern into a Kinesis stream.

## 4. HAZARD-STREAM-012 (PROPOSED) — root CA custody & compromise blast radius

Fleet-wide scope, distinct from the device-level HAZARD-STREAM-010/011.
Also documented as a code-adjacent docstring in `modules/ca/main.tf`
(this repo's existing convention for where hazards live). Not self-closed.

**Mitigated so far:** EFS at-rest encryption
(`aws_efs_file_system.ca_state`, `encrypted = true`); the CA private key
never leaves step-ca's own process -- nothing in this Terraform handles
it directly.

**NOT mitigated -- two distinct gaps, surfaced while answering this
hazard, not assumed away:**
1. `/roots.pem` (step-ca's public root-cert endpoint) shares network
   exposure with the CA's admin/signing/ACME API -- same port, same
   security group, same internal-only NLB. This is currently
   OVER-restricted to the point §1's documented bootstrap flow (an
   operator running `curl .../roots.pem`) is not actually reachable
   without separate VPN/bastion access into the VPC -- a real
   inconsistency between what this document describes and what
   `modules/ca`'s security group actually permits. Needs an explicit
   decision (narrow public proxy for just that one path / require
   bastion access / something else), not a silent fix.
2. No fleet-wide CA-compromise recovery runbook exists: no
   re-issuance-at-scale process, no plan for physically-deployed edge
   appliances (real hospital hardware) that cannot promptly reach a
   re-pointed control plane, no CRL/OCSP or equivalent revocation signal
   beyond the per-device `reattest()` gaps HAZARD-STREAM-011 already
   documents. A device unable to re-enroll during such an event keeps
   operating on stale local data forwarding -- a clinical availability
   concern, not just an infrastructure one.

## 5. Explicitly NOT built in this pass

- **The provisioning API's own admin/token-issuance path** — `modules/
  provisioning-api` implements `/enroll` and `/reattest` (the device-facing
  contract), but "how does an operator or fleet system mint a new
  single-use token for a specific device before shipping it" is a
  separate admin capability not built here. Flagged, not silently assumed.
- **A Terraform-to-k3s-Secret automation pipeline** (see §1).
- **Multi-region/HA for step-ca** — single Fargate task, single EFS
  filesystem. Fine for initial fleet scale; revisit if uptime requirements
  harden.
- **A real production HL7/monitor-simulator equivalent** — only the local
  docker-compose one exists (Phase 5-Stream Section C, prior commit).

Every one of these is a scope boundary, not an oversight — call out
explicitly rather than silently expanding this pass further.
