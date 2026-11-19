"""
HD-E7: the labelled demonstration staleness profile.

- It sets every window the scoring gate requires, with positive values.
- docker-compose.yml's fallbacks equal the profile, and a host value wins.
- The values themselves are a demonstration profile, NOT clinically validated;
  src/ must never carry a default (production refuses to start without them).
"""

from __future__ import annotations

import re
from pathlib import Path

import yaml
from domain.services.scoring_gate import window_env_names

ROOT = Path(__file__).resolve().parents[2]
PROFILE = ROOT / "deploy" / "profiles" / "news2-staleness.demo.env"
COMPOSE = ROOT / "docker-compose.yml"


def _profile() -> dict[str, str]:
    pairs = (
        line.split("=", 1)
        for line in PROFILE.read_text(encoding="utf-8").splitlines()
        if line and not line.startswith("#")
    )
    return {k.strip(): v.strip() for k, v in pairs}


def test_profile_covers_every_required_window() -> None:
    # Derived from the scoring gate itself, so a new required type cannot
    # slip past this check.
    expected = set(window_env_names())
    values = _profile()
    assert set(values) == expected
    assert all(int(v) > 0 for v in values.values())


def test_profile_is_labelled_not_clinically_validated() -> None:
    assert "NOT CLINICALLY VALIDATED" in PROFILE.read_text(encoding="utf-8")


def test_compose_fallbacks_equal_the_profile_and_host_values_win() -> None:
    env = yaml.safe_load(COMPOSE.read_text(encoding="utf-8"))["services"]["gateway"]["environment"]
    for name, value in _profile().items():
        assert env[name] == f"${{{name}:-{value}}}", name


def test_src_carries_no_default_window() -> None:
    # Any literal staleness variable name followed by a default argument, in
    # getenv / environ.get / setdefault form, or an assignment of a number.
    patterns = [
        re.compile(r"NEWS2_STALENESS_WINDOW_\w+_SECONDS[\"']\s*,\s*[\"']?\d"),
        re.compile(r"NEWS2_STALENESS_WINDOW_\w+_SECONDS\s*=\s*[\"']?\d"),
    ]
    for py in (ROOT / "src").rglob("*.py"):
        text = py.read_text(encoding="utf-8")
        for pattern in patterns:
            assert not pattern.search(text), (py, pattern.pattern)


def test_default_pattern_catches_the_common_forms() -> None:
    samples = [
        'os.getenv("NEWS2_STALENESS_WINDOW_SPO2_SECONDS", "300")',
        "os.environ.get('NEWS2_STALENESS_WINDOW_SPO2_SECONDS', 300)",
        "NEWS2_STALENESS_WINDOW_SPO2_SECONDS = 300",
    ]
    patterns = [
        re.compile(r"NEWS2_STALENESS_WINDOW_\w+_SECONDS[\"']\s*,\s*[\"']?\d"),
        re.compile(r"NEWS2_STALENESS_WINDOW_\w+_SECONDS\s*=\s*[\"']?\d"),
    ]
    for sample in samples:
        assert any(p.search(sample) for p in patterns), sample
