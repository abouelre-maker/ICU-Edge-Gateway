"""
Integration Tests — Re-Attestation Loop ASGI Lifespan Wiring
(Phase 5 Section B follow-up).

Verifies main.py's lifespan starts/cancels a reattestation_loop() task when
PROVISIONING_ENABLED=true, and leaves it off by default. Mirrors
test_main_mqtt_lifespan.py's pattern of driving lifespan() directly.

The interval is set very high (an hour) in the "enabled" tests so the
background task is reliably still asleep (not making a real network call)
when we inspect/tear down the app -- we're testing wiring and clean
cancellation here, not the reattest() logic itself (see
test_reattestation.py for that).
"""

from __future__ import annotations

import asyncio
import datetime

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID
from main import create_app, lifespan


def _write_dummy_ca_pem(tmp_path) -> str:
    """
    A real, loadable (but otherwise meaningless) self-signed CA cert --
    httpx.AsyncClient(verify=path) validates the file exists and parses at
    CONSTRUCTION time, so a nonexistent/fake path would crash the
    background task before it ever reaches its sleep(), which is what
    these tests are actually exercising. No real TLS connection is made
    in these tests (see test_enrollment_client_ca_pinning.py for that).
    """
    key = ec.generate_private_key(ec.SECP256R1())
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "Test CA")])
    now = datetime.datetime.now(datetime.timezone.utc)
    cert = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - datetime.timedelta(hours=1))
        .not_valid_after(now + datetime.timedelta(days=1))
        .sign(key, hashes.SHA256())
    )
    path = tmp_path / "ca-bundle.pem"
    path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    return str(path)


@pytest.mark.integration
class TestReattestationDisabledByDefault:
    async def test_no_background_task_started_when_provisioning_unset(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("PROVISIONING_ENABLED", raising=False)
        app = create_app()

        async with lifespan(app):
            assert app.state.reattestation_task is None


@pytest.mark.integration
class TestReattestationEnabledViaEnv:
    def _set_valid_env(self, monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
        monkeypatch.setenv("PROVISIONING_ENABLED", "true")
        monkeypatch.setenv(
            "PROVISIONING_BOOTSTRAP_URL", "https://control-plane.example.org"
        )
        monkeypatch.setenv(
            "PROVISIONING_CA_BUNDLE_PATH", _write_dummy_ca_pem(tmp_path)
        )
        monkeypatch.setenv("CERT_STORE_PATH", str(tmp_path / "pki"))
        monkeypatch.setenv("REATTESTATION_INTERVAL_SECONDS", "3600")

    async def test_background_task_started_and_running(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path
    ) -> None:
        self._set_valid_env(monkeypatch, tmp_path)
        app = create_app()

        async with lifespan(app):
            assert app.state.reattestation_task is not None
            assert not app.state.reattestation_task.done()

        # After the `async with` block exits, lifespan's shutdown path has
        # cancelled and awaited the task -- it must be finished, not
        # abandoned mid-flight.
        assert app.state.reattestation_task.done()

    async def test_task_is_cleanly_cancelled_on_shutdown_not_abandoned(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path
    ) -> None:
        self._set_valid_env(monkeypatch, tmp_path)
        app = create_app()

        async with lifespan(app):
            task = app.state.reattestation_task
            await asyncio.sleep(0)  # let it reach its sleep()
            assert not task.done()

        # Cancelled cleanly (raised+caught internally, re-raised, awaited
        # by lifespan's shutdown with contextlib.suppress) -- not left
        # running, not raised back out of the `async with` block.
        assert task.cancelled()
