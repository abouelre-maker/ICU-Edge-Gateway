"""
Unit Tests — Runtime Configuration (CORS Origin Allow-List).

IEC 62304 §5.7: Verification of the HAZARD-CORS-001 mitigation.
ISO 14971 HAZARD-CORS-001: A wildcard or empty CORS origin allow-list is a
confidentiality hazard — these tests prove the gateway refuses to start
with an unsafe configuration and correctly parses a valid one.
"""

from __future__ import annotations

import pytest
from config import get_cors_allowed_origins


class TestGetCorsAllowedOriginsDefault:
    """No CORS_ALLOWED_ORIGINS set → safe local-dev default, never a wildcard."""

    def test_falls_back_to_localhost_dev_default_when_unset(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("CORS_ALLOWED_ORIGINS", raising=False)
        assert get_cors_allowed_origins() == ["http://localhost:3000"]


class TestGetCorsAllowedOriginsValid:
    """A well-formed, explicit allow-list is parsed correctly."""

    def test_single_origin(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("CORS_ALLOWED_ORIGINS", "https://ehr.example.org")
        assert get_cors_allowed_origins() == ["https://ehr.example.org"]

    def test_multiple_comma_separated_origins(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv(
            "CORS_ALLOWED_ORIGINS",
            "https://ehr.example.org,https://icu-dashboard.example.org",
        )
        assert get_cors_allowed_origins() == [
            "https://ehr.example.org",
            "https://icu-dashboard.example.org",
        ]

    def test_strips_whitespace_around_origins(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv(
            "CORS_ALLOWED_ORIGINS",
            " https://ehr.example.org , https://icu-dashboard.example.org ",
        )
        assert get_cors_allowed_origins() == [
            "https://ehr.example.org",
            "https://icu-dashboard.example.org",
        ]

    def test_ignores_empty_entries_from_trailing_comma(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("CORS_ALLOWED_ORIGINS", "https://ehr.example.org,")
        assert get_cors_allowed_origins() == ["https://ehr.example.org"]


class TestGetCorsAllowedOriginsRejectsUnsafeValues:
    """HAZARD-CORS-001: wildcard and empty allow-lists must fail closed."""

    def test_rejects_bare_wildcard(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("CORS_ALLOWED_ORIGINS", "*")
        with pytest.raises(ValueError, match="Wildcard '\\*' is prohibited"):
            get_cors_allowed_origins()

    def test_rejects_wildcard_mixed_with_explicit_origins(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("CORS_ALLOWED_ORIGINS", "https://ehr.example.org,*")
        with pytest.raises(ValueError, match="Wildcard '\\*' is prohibited"):
            get_cors_allowed_origins()

    def test_rejects_empty_string(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("CORS_ALLOWED_ORIGINS", "")
        with pytest.raises(ValueError, match="non-empty"):
            get_cors_allowed_origins()

    def test_rejects_whitespace_only_string(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("CORS_ALLOWED_ORIGINS", "   ")
        with pytest.raises(ValueError, match="non-empty"):
            get_cors_allowed_origins()

    def test_rejects_commas_only_string(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("CORS_ALLOWED_ORIGINS", ",,,")
        with pytest.raises(ValueError, match="non-empty"):
            get_cors_allowed_origins()
