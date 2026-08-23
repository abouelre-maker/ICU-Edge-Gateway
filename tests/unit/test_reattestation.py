"""
Unit Tests — infrastructure.provisioning.reattestation.

Covers `_reattest_once` (the per-tick logic, isolated from the sleep loop)
and `reattestation_loop`'s cancellation behavior. Uses the same
httpx.MockTransport pattern as test_enrollment_client.py -- no real network
call, no real waiting (interval_seconds is irrelevant to these tests since
cancellation happens before the first sleep completes).
"""

from __future__ import annotations

import asyncio
import datetime

import httpx
import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.x509.oid import NameOID
from infrastructure.provisioning.cert_store import CertStore, IssuedCredentials
from infrastructure.provisioning.enrollment_client import DeviceEnrollmentClient
from infrastructure.provisioning.reattestation import _reattest_once, reattestation_loop

_BOOTSTRAP_URL = "https://control-plane.example.org/provisioning"


def _valid_cert_pem(key) -> bytes:
    now = datetime.datetime.now(datetime.timezone.utc)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "test-device")])
    cert = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - datetime.timedelta(hours=1))
        .not_valid_after(now + datetime.timedelta(days=30))
        .sign(key, hashes.SHA256())
    )
    return cert.public_bytes(encoding=serialization.Encoding.PEM)


def _store_with_valid_identity(tmp_path) -> CertStore:
    store = CertStore(str(tmp_path / "pki"))
    key = store.load_or_generate_key()
    store.write_issued_credentials(
        IssuedCredentials(
            certificate_pem=_valid_cert_pem(key), ca_chain_pem=_valid_cert_pem(key)
        )
    )
    return store


def _enrollment_client_that_reattests(handler) -> DeviceEnrollmentClient:
    # reattest() ignores this client's own transport entirely (it uses
    # whatever mtls_client is passed to it) -- only exists to satisfy the
    # constructor. See enrollment_client.py::DeviceEnrollmentClient.reattest.
    return DeviceEnrollmentClient(
        _BOOTSTRAP_URL,
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(201))),
    )


@pytest.mark.integration
class TestReattestOnce:
    async def test_skips_when_no_valid_identity(self, tmp_path) -> None:
        store = CertStore(str(tmp_path / "pki"))  # never enrolled
        called = {"n": 0}

        def handler(request: httpx.Request) -> httpx.Response:
            called["n"] += 1
            return httpx.Response(200)

        await _reattest_once(
            cert_store=store,
            enrollment_client=_enrollment_client_that_reattests(handler),
            mtls_client_factory=lambda: httpx.AsyncClient(
                transport=httpx.MockTransport(handler)
            ),
        )

        assert called["n"] == 0  # no call made -- nothing to re-attest with

    async def test_ok_response_does_not_quarantine(self, tmp_path) -> None:
        store = _store_with_valid_identity(tmp_path)

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200)

        await _reattest_once(
            cert_store=store,
            enrollment_client=_enrollment_client_that_reattests(handler),
            mtls_client_factory=lambda: httpx.AsyncClient(
                transport=httpx.MockTransport(handler)
            ),
        )

        assert store.has_valid_identity() is True  # untouched

    async def test_revoked_response_quarantines(self, tmp_path) -> None:
        store = _store_with_valid_identity(tmp_path)

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(401)

        await _reattest_once(
            cert_store=store,
            enrollment_client=_enrollment_client_that_reattests(handler),
            mtls_client_factory=lambda: httpx.AsyncClient(
                transport=httpx.MockTransport(handler)
            ),
        )

        assert store.has_valid_identity() is False  # quarantined
        import os

        assert os.path.exists(store.cert_path + ".revoked")

    async def test_skips_when_key_present_but_no_certificate_at_all(
        self, tmp_path
    ) -> None:
        """
        Phase 5-Stream Section D edge case, distinct from
        test_skips_when_no_valid_identity above (which uses a totally
        fresh store -- no key, no cert): here the device's private key was
        already generated (e.g. a prior process crashed or lost network
        connectivity between key generation and receiving the issued
        certificate from /enroll) but write_issued_credentials() was never
        called, so device.crt does not exist at all.
        cert_store.has_valid_identity() must still report False (see
        test_cert_store.py::TestHasValidIdentity::
        test_false_when_only_key_present for the unit-level guarantee this
        relies on), and _reattest_once must still skip cleanly at the
        orchestration level -- no mTLS client is ever built (there is no
        certificate to present), no network call is attempted.
        """
        store = CertStore(str(tmp_path / "pki"))
        store.load_or_generate_key()  # key exists...
        assert not (tmp_path / "pki" / "device.crt").exists()  # ...cert does not

        called = {"n": 0}

        def handler(request: httpx.Request) -> httpx.Response:
            called["n"] += 1
            return httpx.Response(200)

        await _reattest_once(
            cert_store=store,
            enrollment_client=_enrollment_client_that_reattests(handler),
            mtls_client_factory=lambda: httpx.AsyncClient(
                transport=httpx.MockTransport(handler)
            ),
        )

        assert called["n"] == 0
        assert store.has_valid_identity() is False

    async def test_network_error_is_skipped_not_quarantined(self, tmp_path) -> None:
        store = _store_with_valid_identity(tmp_path)

        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("WAN outage")

        await _reattest_once(
            cert_store=store,
            enrollment_client=_enrollment_client_that_reattests(handler),
            mtls_client_factory=lambda: httpx.AsyncClient(
                transport=httpx.MockTransport(handler)
            ),
        )

        # HAZARD-STREAM-011: a WAN outage must not masquerade as revocation.
        assert store.has_valid_identity() is True


@pytest.mark.integration
class TestReattestationLoopCancellation:
    async def test_cancelling_the_task_stops_the_loop_cleanly(self, tmp_path) -> None:
        store = _store_with_valid_identity(tmp_path)
        ticks = {"n": 0}

        def handler(request: httpx.Request) -> httpx.Response:
            ticks["n"] += 1
            return httpx.Response(200)

        task = asyncio.create_task(
            reattestation_loop(
                cert_store=store,
                bootstrap_url=_BOOTSTRAP_URL,
                interval_seconds=3600,  # long enough that cancellation
                # happens during the initial sleep, not after it
                enrollment_client=_enrollment_client_that_reattests(handler),
                mtls_client_factory=lambda: httpx.AsyncClient(
                    transport=httpx.MockTransport(handler)
                ),
            )
        )
        await asyncio.sleep(0)  # let the task actually start and hit sleep()
        task.cancel()

        with pytest.raises(asyncio.CancelledError):
            await task

        assert ticks["n"] == 0  # cancelled during the first sleep, never ticked
        assert task.cancelled() or task.done()
