"""
Unit Tests — infrastructure.provisioning.bootstrap_cli._main().

Covers the container-entrypoint decision logic (exit codes) without any
real network call: ensure_device_identity is monkeypatched at the
bootstrap_cli module's import site, same technique used throughout this
suite for isolating orchestration from I/O.
"""

from __future__ import annotations

import pytest
from infrastructure.provisioning import bootstrap_cli
from infrastructure.provisioning.enrollment_client import TokenRejectedError


class TestMainDisabledByDefault:
    async def test_returns_0_and_does_nothing_when_disabled(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("PROVISIONING_ENABLED", raising=False)
        called = {"n": 0}

        async def fake_ensure(**kwargs):
            called["n"] += 1

        monkeypatch.setattr(bootstrap_cli, "ensure_device_identity", fake_ensure)

        exit_code = await bootstrap_cli._main()

        assert exit_code == 0
        assert called["n"] == 0


class TestMainConfigurationError:
    async def test_returns_1_when_bootstrap_url_missing(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("PROVISIONING_ENABLED", "true")
        monkeypatch.delenv("PROVISIONING_BOOTSTRAP_URL", raising=False)
        monkeypatch.setenv("ENROLLMENT_TOKEN", "some-token")

        exit_code = await bootstrap_cli._main()

        assert exit_code == 1

    async def test_returns_1_when_token_missing(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("PROVISIONING_ENABLED", "true")
        monkeypatch.setenv(
            "PROVISIONING_BOOTSTRAP_URL", "https://control-plane.example.org"
        )
        monkeypatch.delenv("ENROLLMENT_TOKEN_FILE", raising=False)
        monkeypatch.delenv("ENROLLMENT_TOKEN", raising=False)

        exit_code = await bootstrap_cli._main()

        assert exit_code == 1


class TestMainEnrollmentOutcomes:
    def _set_valid_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("PROVISIONING_ENABLED", "true")
        monkeypatch.setenv(
            "PROVISIONING_BOOTSTRAP_URL", "https://control-plane.example.org"
        )
        monkeypatch.setenv("ENROLLMENT_TOKEN", "valid-token")

    async def test_returns_0_on_successful_enrollment(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        self._set_valid_env(monkeypatch)

        async def fake_ensure(**kwargs):
            return True

        monkeypatch.setattr(bootstrap_cli, "ensure_device_identity", fake_ensure)

        exit_code = await bootstrap_cli._main()

        assert exit_code == 0

    async def test_returns_1_when_enrollment_raises(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        self._set_valid_env(monkeypatch)

        async def fake_ensure(**kwargs):
            raise TokenRejectedError(401, "invalid_or_unauthenticated")

        monkeypatch.setattr(bootstrap_cli, "ensure_device_identity", fake_ensure)

        exit_code = await bootstrap_cli._main()

        assert exit_code == 1
