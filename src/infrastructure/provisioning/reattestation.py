"""
Periodic Re-Attestation Loop — FastAPI Lifespan Background Task.

Phase 5 Section B follow-up: wires DeviceEnrollmentClient.reattest() (and
config.get_reattestation_interval_seconds(), which already existed) to
actually run on an interval, for as long as the ASGI app process is alive.
Before this module, `reattest()` was reachable but never called from
anywhere in this codebase -- HAZARD-STREAM-011's "periodic re-attestation"
mitigation described a check that was never scheduled.

WHY THE LIFESPAN, NOT bootstrap_cli.py: bootstrap_cli.py is a one-shot
pre-flight check that runs BEFORE uvicorn starts and then exits
(docker/entrypoint.sh's `set -e`); "is this device still trusted" is a
continuous concern for as long as the appliance is serving traffic, which
matches the running ASGI app's lifetime, not a one-shot startup check.
See main.py's lifespan() for how this task is started/cancelled.

ISO 14971 HAZARD-STREAM-011 (see cert_store.py -- still PROPOSED, pending
human sign-off; this module makes the mitigation it already describes
actually run, it does not add new mitigation beyond what that hazard
already specified):
  - Now covered: the interval check runs continuously while the app is up.
  - STILL NOT covered by this loop (both already documented in
    cert_store.py, restated here for locality): (a) an already-open mTLS
    session/connection is not torn down mid-flight by a revocation
    discovered on the next reattest() tick -- revocation is only acted on
    at the next scheduled check, not instantaneously; (b) a device that is
    network-partitioned from the control plane cannot complete a
    reattest() call at all and keeps operating on its last-known-valid
    certificate until it expires naturally.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable

import httpx
import structlog

from infrastructure.provisioning.cert_store import CertStore
from infrastructure.provisioning.enrollment_client import (
    DeviceEnrollmentClient,
    EnrollmentNetworkError,
)

_log: structlog.BoundLogger = structlog.get_logger(__name__)


async def _reattest_once(
    *,
    cert_store: CertStore,
    enrollment_client: DeviceEnrollmentClient,
    mtls_client_factory: Callable[[], httpx.AsyncClient],
) -> None:
    """
    Single re-attestation attempt. Isolated from the sleep loop below so it
    can be unit-tested directly without waiting on real intervals.
    """
    if not cert_store.has_valid_identity():
        # Nothing to re-attest with -- e.g. quarantined by a previous tick,
        # or enrollment never completed. Not an error; just skip this tick.
        _log.info("provisioning.reattestation_loop.skipped_no_identity")
        return

    mtls_client = mtls_client_factory()
    try:
        result = await enrollment_client.reattest(mtls_client)
    except EnrollmentNetworkError:
        # Per HAZARD-STREAM-011: a network failure is NOT treated as
        # revocation. Log and wait for the next tick.
        _log.warning("provisioning.reattestation_loop.network_error_skipped")
        return
    finally:
        await mtls_client.aclose()

    if result.revoked:
        cert_store.quarantine()
        _log.warning(
            "provisioning.reattestation_loop.quarantined_after_revocation",
            status_code=result.status_code,
        )
    else:
        _log.info(
            "provisioning.reattestation_loop.ok", status_code=result.status_code
        )


async def reattestation_loop(
    *,
    cert_store: CertStore,
    bootstrap_url: str,
    interval_seconds: float,
    enrollment_client: DeviceEnrollmentClient | None = None,
    mtls_client_factory: Callable[[], httpx.AsyncClient] | None = None,
    ca_bundle_path: str | None = None,
) -> None:
    """
    Runs forever, calling `_reattest_once` every `interval_seconds`, until
    the enclosing asyncio.Task is cancelled (main.py's lifespan does this
    on shutdown and awaits the task so shutdown is clean, not abandoned).

    Sleeps FIRST, then checks: a device's identity is freshly issued right
    before this loop starts (bootstrap_cli.py's enrollment just completed,
    or an existing valid identity was confirmed), so an immediate
    reattest() would only re-confirm what enrollment/startup already
    established.

    `enrollment_client` and `mtls_client_factory` are injectable for
    testing. The default `mtls_client_factory` builds an httpx.AsyncClient
    presenting the device's own issued certificate (cert_store.cert_path /
    cert_store.key_path) and trusting only the control plane's CA chain
    (cert_store.ca_path) -- this is the mTLS leg; enrollment itself
    (before a certificate exists) uses server-authenticated TLS only, per
    enrollment_client.py's docstring.
    """
    owns_client = enrollment_client is None
    client = enrollment_client or DeviceEnrollmentClient(
        bootstrap_url, ca_bundle_path=ca_bundle_path
    )

    def _default_mtls_client_factory() -> httpx.AsyncClient:
        return httpx.AsyncClient(
            cert=(cert_store.cert_path, cert_store.key_path),
            verify=cert_store.ca_path,
            timeout=15.0,
        )

    factory = mtls_client_factory or _default_mtls_client_factory

    try:
        while True:
            await asyncio.sleep(interval_seconds)
            await _reattest_once(
                cert_store=cert_store,
                enrollment_client=client,
                mtls_client_factory=factory,
            )
    except asyncio.CancelledError:
        _log.info("provisioning.reattestation_loop.cancelled")
        raise
    finally:
        if owns_client:
            await client.aclose()
