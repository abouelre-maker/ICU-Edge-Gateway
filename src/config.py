"""
Runtime configuration — environment-driven, fail-closed on unsafe values.

ISO 14971: A misconfigured CORS origin is a confidentiality hazard
(HAZARD-CORS-001). This module refuses to start with a wildcard origin.
"""
from __future__ import annotations

import os
import socket
from dataclasses import dataclass

_DEFAULT_DEV_ORIGINS = ("http://localhost:3000",)


def get_mllp_enabled() -> bool:
    """
    MLLP_ENABLED (default: false). Edge deployments that receive HL7 v2.x
    directly over MLLP (rather than only via HTTP POST /api/v1/ingest) opt
    in explicitly — disabled by default so existing HTTP-only deployments
    are unaffected by Phase 5 Section A.
    """
    return os.getenv("MLLP_ENABLED", "false").strip().lower() in {"1", "true", "yes"}


def get_mllp_host() -> str:
    """MLLP_HOST (default: 0.0.0.0 — edge appliance listens for LAN-side monitors)."""
    # Bandit B104 (hardcoded_bind_all_interfaces): intentional -- this is an
    # edge appliance that must accept MLLP connections from any bedside
    # monitor on the ICU LAN, not a single known peer. Overridable via
    # MLLP_HOST for deployments that want to narrow this.
    return os.getenv("MLLP_HOST", "0.0.0.0")  # nosec B104


def get_mllp_port() -> int:
    """
    MLLP_PORT (default: 2575 — conventional HL7 MLLP port).

    0 is permitted and means "ask the OS for an ephemeral port" (the
    standard asyncio.start_server convention) — used by tests and by
    deployments where the port is discovered after bind rather than fixed.
    """
    raw = os.getenv("MLLP_PORT", "2575")
    try:
        port = int(raw)
    except ValueError as exc:
        raise ValueError(f"MLLP_PORT must be an integer. Got {raw!r}.") from exc
    if not (0 <= port < 65536):
        raise ValueError(f"MLLP_PORT must be between 0 and 65535. Got {port}.")
    return port


def get_mqtt_enabled() -> bool:
    """
    MQTT_ENABLED (default: false). Edge->cloud telemetry publishing is opt-in
    — disabled by default so existing deployments without a configured MQTT
    broker are unaffected by Phase 5 Section A.
    """
    return os.getenv("MQTT_ENABLED", "false").strip().lower() in {"1", "true", "yes"}


@dataclass(frozen=True)
class MQTTConfig:
    """Validated MQTT publisher configuration. Only meaningful when MQTT is enabled."""

    broker_host: str
    broker_port: int
    topic_prefix: str
    client_id: str
    use_tls: bool
    qos: int
    username: str | None
    password: str | None
    publish_interval_seconds: float
    drain_batch_size: int


def get_mqtt_config() -> MQTTConfig:
    """
    Read and validate MQTT_* environment variables.

    ISO 14971: a broker connection with TLS silently disabled is a
    confidentiality/integrity hazard for clinical telemetry leaving the
    edge appliance over an untrusted WAN link. TLS defaults to enabled;
    disabling it (MQTT_USE_TLS=false, e.g. for local-network development
    against a test broker) is permitted but logged loudly by the publisher
    at connect time — this function does not refuse to start, since a
    local-only development broker without TLS is a legitimate use case,
    unlike CORS's wildcard (HAZARD-CORS-001), which has no legitimate
    production use.
    """
    host = os.getenv("MQTT_BROKER_HOST", "localhost")

    port_raw = os.getenv("MQTT_BROKER_PORT", "8883")
    try:
        port = int(port_raw)
    except ValueError as exc:
        raise ValueError(
            f"MQTT_BROKER_PORT must be an integer. Got {port_raw!r}."
        ) from exc
    if not (0 < port < 65536):
        raise ValueError(f"MQTT_BROKER_PORT must be between 1 and 65535. Got {port}.")

    use_tls = os.getenv("MQTT_USE_TLS", "true").strip().lower() in {"1", "true", "yes"}

    qos_raw = os.getenv("MQTT_QOS", "1")
    try:
        qos = int(qos_raw)
    except ValueError as exc:
        raise ValueError(
            f"MQTT_QOS must be an integer (0, 1, or 2). Got {qos_raw!r}."
        ) from exc
    if qos not in (0, 1, 2):
        raise ValueError(f"MQTT_QOS must be 0, 1, or 2 per the MQTT spec. Got {qos}.")

    interval_raw = os.getenv("MQTT_PUBLISH_INTERVAL_SECONDS", "1.0")
    try:
        interval = float(interval_raw)
    except ValueError as exc:
        raise ValueError(
            f"MQTT_PUBLISH_INTERVAL_SECONDS must be a number. Got {interval_raw!r}."
        ) from exc
    if interval <= 0:
        raise ValueError(
            f"MQTT_PUBLISH_INTERVAL_SECONDS must be positive. Got {interval}."
        )

    batch_raw = os.getenv("MQTT_DRAIN_BATCH_SIZE", "50")
    try:
        batch_size = int(batch_raw)
    except ValueError as exc:
        raise ValueError(
            f"MQTT_DRAIN_BATCH_SIZE must be an integer. Got {batch_raw!r}."
        ) from exc
    if batch_size <= 0:
        raise ValueError(f"MQTT_DRAIN_BATCH_SIZE must be positive. Got {batch_size}.")

    return MQTTConfig(
        broker_host=host,
        broker_port=port,
        topic_prefix=os.getenv("MQTT_TOPIC_PREFIX", "icu-edge/vitals"),
        client_id=os.getenv("MQTT_CLIENT_ID", "icu-edge-gateway"),
        use_tls=use_tls,
        qos=qos,
        username=os.getenv("MQTT_USERNAME") or None,
        password=os.getenv("MQTT_PASSWORD") or None,
        publish_interval_seconds=interval,
        drain_batch_size=batch_size,
    )


def get_fhir_subscription_registration_secret() -> str:
    """
    FHIR_SUBSCRIPTION_REGISTRATION_SECRET (required, no default).

    ISO 14971 HAZARD-STREAM-009 (PROPOSED — pending human security/risk-
    management sign-off): POST /api/v1/fhir/Subscription accepts a caller-
    supplied channel.endpoint AND channel.header values, which typically
    carry the caller's own webhook bearer token (see
    infrastructure/fhir/subscription.py). Without authenticating the
    registration request itself, any network-reachable caller could:
      - register a Subscription to receive a copy of every matching
        clinical FHIR Bundle (data exfiltration), or
      - read or delete another caller's Subscription via GET/DELETE
        /api/v1/fhir/Subscription/{id} -- including the channel.header
        credentials embedded in it (credential disclosure; see
        HAZARD-FHIR-004's single-tenant list() note, which this closes
        for the single-Subscription read path too).
    Mitigation: api/v1/fhir_subscription.py requires this pre-shared
    secret (as "Authorization: Bearer <secret>") on every route in that
    router. Fail-closed like CORS (HAZARD-CORS-001): raises rather than
    silently letting requests through when unset, because a missing
    secret here is a misconfiguration, not a legitimate no-auth
    deployment choice.
    """
    secret = os.getenv("FHIR_SUBSCRIPTION_REGISTRATION_SECRET")
    if not secret or not secret.strip():
        raise ValueError(
            "FHIR_SUBSCRIPTION_REGISTRATION_SECRET must be set to a "
            "non-empty pre-shared secret -- the FHIR Subscription "
            "endpoints accept and disclose caller-supplied webhook "
            "credentials and must not be reachable without authenticating "
            "the caller (HAZARD-STREAM-009)."
        )
    return secret


def get_provisioning_enabled() -> bool:
    """
    PROVISIONING_ENABLED (default: false). Phase 5 Section B device-identity
    enrollment is opt-in, exactly like MLLP_ENABLED/MQTT_ENABLED -- disabled
    by default so every existing deployment (and this repo's entire existing
    test suite) is unaffected. When true, the container entrypoint runs the
    enrollment handshake (infrastructure/provisioning/bootstrap.py) before
    uvicorn starts.
    """
    return os.getenv("PROVISIONING_ENABLED", "false").strip().lower() in {
        "1",
        "true",
        "yes",
    }


def get_provisioning_bootstrap_url() -> str:
    """
    PROVISIONING_BOOTSTRAP_URL (required when PROVISIONING_ENABLED=true).

    The control plane's enrollment endpoint, e.g.
    "https://control-plane.example.org/provisioning". The device opens a
    server-authenticated TLS connection to this URL and POSTs its CSR + a
    single-use enrollment token to "{url}/enroll" -- see
    infrastructure/provisioning/enrollment_client.py. Fail-closed: raises
    if unset rather than silently defaulting to something guessable.
    """
    url = os.getenv("PROVISIONING_BOOTSTRAP_URL")
    if not url or not url.strip():
        raise ValueError(
            "PROVISIONING_BOOTSTRAP_URL must be set when PROVISIONING_ENABLED "
            "is true -- the device has no default control plane to enroll "
            "against."
        )
    if not url.startswith("https://"):
        raise ValueError(
            "PROVISIONING_BOOTSTRAP_URL must use https:// -- the enrollment "
            "token and CSR must not be sent over plaintext HTTP."
        )
    return url.rstrip("/")


def get_enrollment_token() -> str:
    """
    The single-use, tenant-scoped enrollment token proving this device is
    authorized to enroll.

    Read from ENROLLMENT_TOKEN_FILE (preferred -- a mounted Secret file,
    e.g. a Kubernetes Secret volume, so the token is never an environment
    variable visible via `docker inspect`/`kubectl describe pod` or process
    listings) if set, else from ENROLLMENT_TOKEN directly (permitted for
    local development only). The token itself is never baked into any
    container image layer -- it is injected at deploy time. Never logged by
    any caller of this function.
    """
    token_file = os.getenv("ENROLLMENT_TOKEN_FILE")
    if token_file:
        try:
            with open(token_file, encoding="utf-8") as fh:
                token = fh.read().strip()
        except OSError as exc:
            raise ValueError(
                f"ENROLLMENT_TOKEN_FILE={token_file!r} could not be read: {exc}"
            ) from exc
        if not token:
            raise ValueError(f"ENROLLMENT_TOKEN_FILE={token_file!r} is empty.")
        return token

    env_token = os.getenv("ENROLLMENT_TOKEN")
    if not env_token or not env_token.strip():
        raise ValueError(
            "Either ENROLLMENT_TOKEN_FILE (preferred -- mounted Secret) or "
            "ENROLLMENT_TOKEN must be set when PROVISIONING_ENABLED is true."
        )
    return env_token.strip()


def get_provisioning_ca_bundle_path() -> str:
    """
    PROVISIONING_CA_BUNDLE_PATH (required when PROVISIONING_ENABLED=true).

    Path to a PEM file containing ONLY the control plane's specific CA
    certificate(s) -- NOT the system/OS default trust store.

    ISO 14971 HAZARD-STREAM-010 (server-authentication leg -- narrows, does
    not close, the existing PROPOSED hazard; see enrollment_client.py):
    without this, DeviceEnrollmentClient trusts any certificate chaining to
    ANY publicly-trusted CA, not specifically the real control plane's. A
    device tricked (DNS hijack, compromised resolver, malicious network at
    a physical deployment site) into resolving PROVISIONING_BOOTSTRAP_URL's
    hostname to an attacker-controlled host holding any publicly-trusted
    cert would hand over its enrollment token and CSR to that host. Pinning
    to this specific bundle closes that gap for the enrollment/reattest
    legs. Fail-closed: raises if unset rather than silently falling back to
    the system bundle -- an operator who forgets to set this must not get a
    device that silently trusts the whole public CA ecosystem instead.
    """
    path = os.getenv("PROVISIONING_CA_BUNDLE_PATH")
    if not path or not path.strip():
        raise ValueError(
            "PROVISIONING_CA_BUNDLE_PATH must be set when PROVISIONING_ENABLED "
            "is true -- the device must not trust the system default CA bundle "
            "for the enrollment/reattest handshakes (HAZARD-STREAM-010)."
        )
    return path.strip()


def get_device_common_name() -> str:
    """
    DEVICE_COMMON_NAME (default: the container/pod hostname).

    Identifies this device in its CSR (infrastructure/provisioning/
    device_identity.py's build_csr()). A production deployment should set
    this explicitly to a stable hardware serial or pre-provisioned device
    UUID (Kubernetes pod hostnames are not stable device identity -- a
    rescheduled pod gets a new hostname) -- the hostname default here is a
    local-development convenience, not a production recommendation.
    """
    return os.getenv("DEVICE_COMMON_NAME") or socket.gethostname()


def get_cert_store_path() -> str:
    """
    CERT_STORE_PATH (default: /var/lib/icu-edge-gateway/pki).

    Directory holding the device's private key and issued certificate.
    MUST be a mounted volume (Kubernetes Secret/PVC) -- never a path inside
    the image's writable layer -- so the private key survives container
    restarts without ever having been baked into an image layer. This
    module does not enforce the mount itself (that is a deployment-time
    guarantee -- see deploy/k3s/edge-appliance.yaml); it only reads/writes
    whatever path is configured.
    """
    return os.getenv("CERT_STORE_PATH", "/var/lib/icu-edge-gateway/pki")


def get_provisioning_max_enroll_attempts() -> int:
    """
    PROVISIONING_MAX_ENROLL_ATTEMPTS (default: 5).

    ISO 14971 HAZARD-STREAM-010 mitigation (see
    infrastructure/provisioning/enrollment_client.py): bounds how many
    times this device will call the control plane's bootstrap endpoint
    for a single enrollment attempt before giving up, so a misconfigured
    or looping device cannot itself become a source of repeated-call abuse
    against that endpoint.
    """
    raw = os.getenv("PROVISIONING_MAX_ENROLL_ATTEMPTS", "5")
    try:
        attempts = int(raw)
    except ValueError as exc:
        raise ValueError(
            f"PROVISIONING_MAX_ENROLL_ATTEMPTS must be an integer. Got {raw!r}."
        ) from exc
    if attempts < 1:
        raise ValueError(
            f"PROVISIONING_MAX_ENROLL_ATTEMPTS must be >= 1. Got {attempts}."
        )
    return attempts


def get_reattestation_interval_seconds() -> float:
    """
    REATTESTATION_INTERVAL_SECONDS (default: 3600 -- hourly).

    ISO 14971 HAZARD-STREAM-011 mitigation (see
    infrastructure/provisioning/enrollment_client.py's reattest()):
    revocation path for a decommissioned/compromised appliance. The device
    periodically presents its current mTLS certificate to the control
    plane; a 401/403 response means the certificate has been revoked, and
    the device must stop using it (see CertStore.quarantine()) rather than
    continue operating on a trust the control plane has withdrawn.
    """
    raw = os.getenv("REATTESTATION_INTERVAL_SECONDS", "3600")
    try:
        interval = float(raw)
    except ValueError as exc:
        raise ValueError(
            f"REATTESTATION_INTERVAL_SECONDS must be a number. Got {raw!r}."
        ) from exc
    if interval <= 0:
        raise ValueError(
            f"REATTESTATION_INTERVAL_SECONDS must be positive. Got {interval}."
        )
    return interval


def get_cors_allowed_origins() -> list[str]:
    """
    Read CORS_ALLOWED_ORIGINS (comma-separated) from the environment.

    Raises ValueError if a wildcard is configured — CORS must be an
    explicit allow-list of trusted EHR/frontend origins in production.
    Falls back to a local-dev default only when unset.
    """
    raw = os.getenv("CORS_ALLOWED_ORIGINS")
    if raw is None:
        return list(_DEFAULT_DEV_ORIGINS)

    origins = [origin.strip() for origin in raw.split(",") if origin.strip()]
    if not origins or "*" in origins:
        raise ValueError(
            "CORS_ALLOWED_ORIGINS must be a non-empty, comma-separated "
            "allow-list of explicit origins. Wildcard '*' is prohibited "
            "(HAZARD-CORS-001)."
        )
    return origins
