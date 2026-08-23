"""
Integration Tests — Mock Control Plane vs. the REAL DeviceEnrollmentClient.

This is the one test in this repo that proves deploy/local/mock_control_
plane/app.py actually satisfies the protocol contract enrollment_client.py
codifies on the device side -- not by re-reading both sides' source and
eyeballing agreement, but by driving the real DeviceEnrollmentClient class
against the real mock app in-process (httpx.ASGITransport, no Docker
needed to run this specific test -- Docker networking itself is NOT
exercised here, see deploy/ for that).

deploy/local/mock_control_plane is not on sys.path via pytest's normal
pythonpath config (that's set to ["src"] for the application, not this
dev-only tooling) -- inserted manually below.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import httpx
import pytest
from cryptography.hazmat.primitives import serialization

_MOCK_CP_DIR = Path(__file__).resolve().parents[2] / "deploy" / "local" / "mock_control_plane"
if str(_MOCK_CP_DIR) not in sys.path:
    sys.path.insert(0, str(_MOCK_CP_DIR))


@pytest.fixture
def mock_app(tmp_path, monkeypatch):
    """
    Both generate_certs.py and app.py read MOCK_CP_CERT_DIR (default
    /tmp -- the real container path, see Dockerfile) for where the mock
    CA lives, specifically so a test can redirect both to the SAME
    directory via one env var rather than patching two separate hardcoded
    constants that could drift apart. Set before either module is
    imported, since both compute their path constants at import time.
    """
    monkeypatch.setenv("MOCK_CP_CERT_DIR", str(tmp_path))

    import generate_certs

    # Same module-caching caveat as app.py below: generate_certs's path
    # constants were frozen at ITS first import in this test session too.
    monkeypatch.setattr(generate_certs, "_CA_KEY_PATH", str(tmp_path / "ca.key"))
    monkeypatch.setattr(generate_certs, "_CA_CERT_PATH", str(tmp_path / "ca.crt"))
    monkeypatch.setattr(generate_certs, "_SERVER_KEY_PATH", str(tmp_path / "server.key"))
    monkeypatch.setattr(generate_certs, "_SERVER_CERT_PATH", str(tmp_path / "server.crt"))
    generate_certs.main()

    import app as mock_cp_app

    # app.py's module-level path constants were computed at its FIRST
    # import in this test session (module caching -- re-importing here
    # does not re-run that code), so re-point them explicitly rather than
    # relying on the env var a second time.
    monkeypatch.setattr(mock_cp_app, "_CA_KEY_PATH", str(tmp_path / "ca.key"))
    monkeypatch.setattr(mock_cp_app, "_CA_CERT_PATH", str(tmp_path / "ca.crt"))
    ca_key, ca_cert = mock_cp_app._load_ca()
    monkeypatch.setattr(mock_cp_app, "_CA_KEY", ca_key)
    monkeypatch.setattr(mock_cp_app, "_CA_CERT", ca_cert)
    monkeypatch.setattr(
        mock_cp_app, "_CA_CERT_PEM", ca_cert.public_bytes(serialization.Encoding.PEM)
    )
    monkeypatch.setattr(
        mock_cp_app,
        "_TOKENS",
        mock_cp_app._TokenStore(valid_tokens={"dev-token-001", "single-use-token"}),
    )
    monkeypatch.setattr(mock_cp_app, "_REVOKED_DEVICES", {})

    return mock_cp_app.app


@pytest.fixture
def real_csr_pem():
    from infrastructure.provisioning.device_identity import (
        build_csr,
        generate_private_key,
    )

    key = generate_private_key()
    return build_csr(key, common_name="contract-test-device")


@pytest.mark.integration
class TestMockControlPlaneMatchesDeviceContract:
    async def test_enroll_happy_path_via_real_enrollment_client(
        self, mock_app, real_csr_pem
    ) -> None:
        from infrastructure.provisioning.enrollment_client import DeviceEnrollmentClient

        http_client = httpx.AsyncClient(
            transport=httpx.ASGITransport(app=mock_app), base_url="https://mock-control-plane"
        )
        client = DeviceEnrollmentClient("https://mock-control-plane", http_client=http_client)

        credentials = await client.enroll("dev-token-001", real_csr_pem)

        assert b"BEGIN CERTIFICATE" in credentials.certificate_pem
        assert b"BEGIN CERTIFICATE" in credentials.ca_chain_pem
        await client.aclose()

    async def test_reused_token_yields_409_via_real_enrollment_client(
        self, mock_app, real_csr_pem
    ) -> None:
        from infrastructure.provisioning.enrollment_client import (
            DeviceEnrollmentClient,
            TokenRejectedError,
        )

        http_client = httpx.AsyncClient(
            transport=httpx.ASGITransport(app=mock_app), base_url="https://mock-control-plane"
        )
        client = DeviceEnrollmentClient(
            "https://mock-control-plane", http_client=http_client, max_attempts=1
        )

        await client.enroll("single-use-token", real_csr_pem)  # first redemption succeeds

        with pytest.raises(TokenRejectedError) as exc_info:
            await client.enroll("single-use-token", real_csr_pem)  # genuinely rejected, not just documented

        assert exc_info.value.status_code == 409
        assert exc_info.value.reason == "already_used"
        await client.aclose()

    async def test_two_devices_racing_the_same_token_only_one_succeeds(
        self, mock_app
    ) -> None:
        """
        Phase 5-Stream Section D edge case: unlike the sequential-reuse test
        above (redeem, THEN redeem again), this fires two DISTINCT devices'
        enroll() calls at the mock control plane CONCURRENTLY
        (asyncio.gather, not awaited one after another) for the SAME
        single-use token, to prove _TokenStore.redeem's check-and-set
        happens under one lock acquisition (app.py's actual single-use
        guarantee) rather than merely working when nothing overlaps.
        Exactly one of the two must receive a signed certificate; the other
        must receive a genuine 409, never both succeeding and never both
        failing.
        """
        from infrastructure.provisioning.device_identity import (
            build_csr,
            generate_private_key,
        )
        from infrastructure.provisioning.enrollment_client import (
            DeviceEnrollmentClient,
            TokenRejectedError,
        )

        csr_device_a = build_csr(generate_private_key(), common_name="racer-device-a")
        csr_device_b = build_csr(generate_private_key(), common_name="racer-device-b")

        def _client() -> DeviceEnrollmentClient:
            return DeviceEnrollmentClient(
                "https://mock-control-plane",
                http_client=httpx.AsyncClient(
                    transport=httpx.ASGITransport(app=mock_app),
                    base_url="https://mock-control-plane",
                ),
                max_attempts=1,
            )

        client_a = _client()
        client_b = _client()

        results = await asyncio.gather(
            client_a.enroll("single-use-token", csr_device_a),
            client_b.enroll("single-use-token", csr_device_b),
            return_exceptions=True,
        )

        successes = [r for r in results if not isinstance(r, BaseException)]
        rejections = [r for r in results if isinstance(r, TokenRejectedError)]
        other_errors = [
            r for r in results if isinstance(r, BaseException) and r not in rejections
        ]

        assert other_errors == []
        assert len(successes) == 1, (
            "Exactly one racer must be issued a certificate -- "
            f"got {len(successes)} successes out of 2 concurrent redemptions."
        )
        assert len(rejections) == 1
        assert rejections[0].status_code == 409
        assert rejections[0].reason == "already_used"

        await client_a.aclose()
        await client_b.aclose()

    async def test_unknown_token_yields_401_via_real_enrollment_client(
        self, mock_app, real_csr_pem
    ) -> None:
        from infrastructure.provisioning.enrollment_client import (
            DeviceEnrollmentClient,
            TokenRejectedError,
        )

        http_client = httpx.AsyncClient(
            transport=httpx.ASGITransport(app=mock_app), base_url="https://mock-control-plane"
        )
        client = DeviceEnrollmentClient(
            "https://mock-control-plane", http_client=http_client, max_attempts=1
        )

        with pytest.raises(TokenRejectedError) as exc_info:
            await client.enroll("never-issued-token", real_csr_pem)

        assert exc_info.value.status_code == 401
        await client.aclose()

    async def test_reattest_ok_then_revoked_via_real_enrollment_client(
        self, mock_app
    ) -> None:
        from infrastructure.provisioning.enrollment_client import DeviceEnrollmentClient

        http_client = httpx.AsyncClient(
            transport=httpx.ASGITransport(app=mock_app), base_url="https://mock-control-plane"
        )
        client = DeviceEnrollmentClient("https://mock-control-plane", http_client=http_client)

        mtls_client = httpx.AsyncClient(
            transport=httpx.ASGITransport(app=mock_app),
            base_url="https://mock-control-plane",
            headers={"X-Mock-Device-Id": "contract-test-device"},
        )

        result_before = await client.reattest(mtls_client)
        assert result_before.revoked is False

        revoke_client = httpx.AsyncClient(
            transport=httpx.ASGITransport(app=mock_app), base_url="https://mock-control-plane"
        )
        await revoke_client.post("/revoke/contract-test-device")

        result_after = await client.reattest(mtls_client)
        assert result_after.revoked is True

        await client.aclose()
        await mtls_client.aclose()
        await revoke_client.aclose()
