"""
Enrollment Bootstrap Orchestration — Container Entrypoint Step.

Phase 5 Section B, step 3. Called by docker/entrypoint.sh BEFORE uvicorn
starts (not from inside the FastAPI app/lifespan -- enrollment must
complete before the appliance is considered "up", and it needs no HTTP
server of its own running to do its job). See bootstrap_cli.py for the
actual `python -m` entrypoint invoked by the container.

Idempotent: if a valid (unexpired, non-quarantined) device identity
already exists in the mounted cert store, this is a no-op -- no network
call is made, no new key is generated. This matters because the
entrypoint runs on EVERY container start, not just the first: a normal pod
restart must not re-enroll (which would burn a fresh single-use token it
doesn't have) or regenerate a key that delivery/mTLS wiring elsewhere may
already be using.
"""

from __future__ import annotations

import structlog

from infrastructure.provisioning.cert_store import CertStore
from infrastructure.provisioning.device_identity import build_csr
from infrastructure.provisioning.enrollment_client import DeviceEnrollmentClient

_log: structlog.BoundLogger = structlog.get_logger(__name__)


async def ensure_device_identity(
    *,
    cert_store: CertStore,
    bootstrap_url: str,
    enrollment_token: str,
    device_common_name: str,
    enrollment_client: DeviceEnrollmentClient | None = None,
    max_attempts: int = 5,
    ca_bundle_path: str | None = None,
    expected_hostname: str | None = None,
) -> bool:
    """
    Ensure this device has a valid mTLS identity, enrolling if necessary.

    Returns True if enrollment was actually performed, False if an
    existing valid identity was found and reused (the common, expected
    case on every restart after the first successful boot).

    `enrollment_client` is injectable for testing (an httpx.MockTransport-
    backed client) -- if omitted, a real DeviceEnrollmentClient talking to
    `bootstrap_url` is constructed and closed by this function.
    `ca_bundle_path`/`expected_hostname` are forwarded to that constructed
    client (see enrollment_client.py's HAZARD-STREAM-010 update) and are
    ignored when `enrollment_client` is injected.
    """
    if cert_store.has_valid_identity():
        _log.info("provisioning.bootstrap.identity_already_valid")
        return False

    _log.info("provisioning.bootstrap.starting", bootstrap_url=bootstrap_url)

    key = cert_store.load_or_generate_key()
    csr_pem = build_csr(key, common_name=device_common_name)

    owns_client = enrollment_client is None
    client = enrollment_client or DeviceEnrollmentClient(
        bootstrap_url,
        max_attempts=max_attempts,
        ca_bundle_path=ca_bundle_path,
        expected_hostname=expected_hostname,
    )
    try:
        credentials = await client.enroll(enrollment_token, csr_pem)
    finally:
        if owns_client:
            await client.aclose()

    cert_store.write_issued_credentials(credentials)
    _log.info("provisioning.bootstrap.complete")
    return True
