"""
API-key authentication for HTTP routes and the live WebSocket (F-01, F-08; REQ-SEC-001).

STATUS: wired (2026-11-19, HD-E6 option 1). create_app() adds
`require_api_key` to /api/v1/ingest and /api/v1/vitals, the lifespan calls
config.validate_gateway_auth_config() (fail closed), and WS /api/v1/live/vitals
calls `authorize_websocket` before accepting.

Keys come from GATEWAY_API_KEYS (comma-separated, each ≥ 32 characters) and
are compared as SHA-256 digests with hmac.compare_digest over bytes, so a
non-ASCII presented key yields 401, never a TypeError / 500 (cf. F-06).
"""

from __future__ import annotations

import hashlib
import hmac

from config import get_cors_allowed_origins, get_gateway_api_keys
from fastapi import HTTPException, Request, WebSocket, status

_WS_POLICY_VIOLATION = 1008


def _digest(value: str) -> bytes:
    return hashlib.sha256(value.encode("utf-8", errors="surrogateescape")).digest()


def key_is_valid(presented: str) -> bool:
    candidate = _digest(presented)
    # Compare against every key (no early exit) to keep timing independent of position.
    matches = [hmac.compare_digest(candidate, _digest(k)) for k in get_gateway_api_keys()]
    return any(matches)


def _bearer(value: str) -> str:
    scheme, _, token = value.partition(" ")
    return token.strip() if scheme.lower() == "bearer" else ""


async def require_api_key(request: Request) -> None:
    """FastAPI dependency: 401 unless `Authorization: Bearer <key>` is valid."""
    token = _bearer(request.headers.get("Authorization", ""))
    if not token or not key_is_valid(token):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Valid API key required.",
            headers={"WWW-Authenticate": "Bearer"},
        )


async def authorize_websocket(websocket: WebSocket) -> bool:
    """
    F-08: require a valid key (Authorization header or `access_token` query
    parameter — browsers cannot set headers on WebSockets) AND, when an Origin
    header is present, an Origin on the CORS allow-list. Closes with 1008 and
    returns False when refused.
    """
    candidates = [
        _bearer(websocket.headers.get("Authorization", "")),
        websocket.query_params.get("access_token", ""),
    ]
    token_ok = any(key_is_valid(t) for t in candidates if t)
    origin = websocket.headers.get("Origin")
    origin_ok = origin is None or origin in get_cors_allowed_origins()
    if not token_ok or not origin_ok:
        await websocket.close(code=_WS_POLICY_VIOLATION)
        return False
    return True
