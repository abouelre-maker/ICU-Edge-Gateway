"""
Integration Tests — infrastructure.provisioning.bootstrap.ensure_device_identity.

Covers the orchestration layer: skip-if-already-enrolled (the common case
on every restart after the first successful boot) and the full
generate-key -> CSR -> enroll -> persist flow, using the same
httpx.MockTransport pattern as test_enrollment_client.py.
"""

from __future__ import annotations

import datetime

import httpx
import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.x509.oid import NameOID
from infrastructure.provisioning.bootstrap import ensure_device_identity
from infrastructure.provisioning.cert_store import CertStore, IssuedCredentials
from infrastructure.provisioning.enrollment_client import (
    DeviceEnrollmentClient,
    EnrollmentNetworkError,
    TokenRejectedError,
)

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


@pytest.mark.integration
class TestSkipWhenAlreadyEnrolled:
    async def test_no_network_call_when_valid_identity_exists(self, tmp_path) -> None:
        store = CertStore(str(tmp_path / "pki"))
        key = store.load_or_generate_key()
        store.write_issued_credentials(
            IssuedCredentials(
                certificate_pem=_valid_cert_pem(key), ca_chain_pem=_valid_cert_pem(key)
            )
        )
        call_count = {"n": 0}

        def handler(request: httpx.Request) -> httpx.Response:
            call_count["n"] += 1
            return httpx.Response(201, json={"certificate_pem": "x", "ca_chain_pem": "y"})

        client = DeviceEnrollmentClient(
            _BOOTSTRAP_URL, http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler))
        )

        performed = await ensure_device_identity(
            cert_store=store,
            bootstrap_url=_BOOTSTRAP_URL,
            enrollment_token="unused-token",
            device_common_name="edge-device-001",
            enrollment_client=client,
        )

        assert performed is False
        assert call_count["n"] == 0


@pytest.mark.integration
class TestFullEnrollmentFlow:
    async def test_generates_key_enrolls_and_persists_credentials(self, tmp_path) -> None:
        store = CertStore(str(tmp_path / "pki"))
        assert store.has_valid_identity() is False

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                201,
                json={
                    "certificate_pem": "-----BEGIN CERTIFICATE-----\nissued\n-----END CERTIFICATE-----\n",
                    "ca_chain_pem": "-----BEGIN CERTIFICATE-----\nca\n-----END CERTIFICATE-----\n",
                },
            )

        client = DeviceEnrollmentClient(
            _BOOTSTRAP_URL, http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler))
        )

        performed = await ensure_device_identity(
            cert_store=store,
            bootstrap_url=_BOOTSTRAP_URL,
            enrollment_token="one-time-token",
            device_common_name="edge-device-002",
            enrollment_client=client,
        )

        assert performed is True
        import os

        assert os.path.exists(store.key_path)
        assert os.path.exists(store.cert_path)
        assert os.path.exists(store.ca_path)
        with open(store.cert_path, "rb") as fh:
            assert b"issued" in fh.read()

    async def test_token_rejected_propagates_and_writes_nothing(self, tmp_path) -> None:
        store = CertStore(str(tmp_path / "pki"))

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(401)

        client = DeviceEnrollmentClient(
            _BOOTSTRAP_URL, http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler))
        )

        with pytest.raises(TokenRejectedError):
            await ensure_device_identity(
                cert_store=store,
                bootstrap_url=_BOOTSTRAP_URL,
                enrollment_token="expired-token",
                device_common_name="edge-device-003",
                enrollment_client=client,
            )

        assert store.has_valid_identity() is False
        import os

        assert not os.path.exists(store.cert_path)

    async def test_network_interruption_propagates_after_retries(self, tmp_path) -> None:
        store = CertStore(str(tmp_path / "pki"))

        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("mid-handshake interruption")

        client = DeviceEnrollmentClient(
            _BOOTSTRAP_URL,
            http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
            max_attempts=2,
            base_backoff_seconds=0.001,
        )

        with pytest.raises(EnrollmentNetworkError):
            await ensure_device_identity(
                cert_store=store,
                bootstrap_url=_BOOTSTRAP_URL,
                enrollment_token="valid-token",
                device_common_name="edge-device-004",
                enrollment_client=client,
            )

        assert store.has_valid_identity() is False
