"""
F-12 / REQ-SEC-002: patient identifiers never reach the logs in clear.

A structlog processor replaces the value of identifier-bearing keys with a
keyed pseudonym (HMAC-SHA256, 12 hex chars). The same patient gets the same
pseudonym within one key, so log lines can still be correlated. The key comes
from LOG_PSEUDONYM_KEY when set (stable across restarts); otherwise a random
per-process key is used.
"""

from __future__ import annotations

import hashlib
import hmac
import os
import secrets
from collections.abc import MutableMapping
from typing import Any

import structlog

_IDENTIFIER_KEYS = frozenset({"patient_id", "patient", "mrn", "criteria"})
_NOT_IDENTIFYING = frozenset({"UNKNOWN", "Bundle", ""})
_KEY = os.getenv("LOG_PSEUDONYM_KEY", "").encode("utf-8") or secrets.token_bytes(32)
_installed = False


def pseudonym(value: str) -> str:
    return "pid:" + hmac.new(_KEY, value.encode("utf-8"), hashlib.sha256).hexdigest()[:12]


def pseudonymize_identifiers(
    _logger: Any, _method: str, event_dict: MutableMapping[str, Any]
) -> MutableMapping[str, Any]:
    for key in _IDENTIFIER_KEYS & event_dict.keys():
        value = event_dict[key]
        if value is not None and str(value) not in _NOT_IDENTIFYING:
            event_dict[key] = pseudonym(str(value))
    return event_dict


def install() -> None:
    """Prepend the processor to the active structlog configuration once."""
    global _installed
    if _installed:
        return
    processors = list(structlog.get_config()["processors"])
    structlog.configure(processors=[pseudonymize_identifiers, *processors])
    _installed = True
