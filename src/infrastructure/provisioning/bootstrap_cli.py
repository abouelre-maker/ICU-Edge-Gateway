"""
`python -m infrastructure.provisioning.bootstrap_cli` — Container Entrypoint.

Phase 5 Section B, step 3. Run by docker/entrypoint.sh BEFORE uvicorn
starts. Opt-in (config.get_provisioning_enabled(), default false): existing
deployments that don't set PROVISIONING_ENABLED=true get a no-op exit(0)
here, same "disabled by default" convention as MLLP/MQTT
(config.get_mllp_enabled()/get_mqtt_enabled()) -- this feature does not
change behavior for anyone who hasn't opted in.

Exit codes: 0 = ready to start uvicorn (either enrolled just now, or
already had a valid identity). Non-zero = enrollment failed; the
entrypoint script must NOT start uvicorn in that case (an edge appliance
serving clinical traffic without having completed its own identity
bootstrap, when that bootstrap was explicitly required, is a
misconfiguration that should fail loudly at startup, not silently skip).
"""

from __future__ import annotations

import asyncio
import sys

import structlog
from config import (
    get_cert_store_path,
    get_device_common_name,
    get_enrollment_token,
    get_provisioning_bootstrap_url,
    get_provisioning_enabled,
    get_provisioning_max_enroll_attempts,
)

from infrastructure.provisioning.bootstrap import ensure_device_identity
from infrastructure.provisioning.cert_store import CertStore
from infrastructure.provisioning.enrollment_client import EnrollmentError

_log: structlog.BoundLogger = structlog.get_logger(__name__)


async def _main() -> int:
    if not get_provisioning_enabled():
        _log.info("provisioning.bootstrap_cli.disabled_skip")
        return 0

    try:
        bootstrap_url = get_provisioning_bootstrap_url()
        enrollment_token = get_enrollment_token()
        cert_store = CertStore(get_cert_store_path())
        max_attempts = get_provisioning_max_enroll_attempts()
        device_common_name = get_device_common_name()
    except ValueError:
        _log.exception("provisioning.bootstrap_cli.configuration_error")
        return 1

    try:
        await ensure_device_identity(
            cert_store=cert_store,
            bootstrap_url=bootstrap_url,
            enrollment_token=enrollment_token,
            device_common_name=device_common_name,
            max_attempts=max_attempts,
        )
    except EnrollmentError:
        _log.exception("provisioning.bootstrap_cli.enrollment_failed")
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(_main()))
