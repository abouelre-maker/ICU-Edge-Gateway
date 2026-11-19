"""
API-key authentication for HTTP routes and the live WebSocket (F-01, F-08).

STATUS: implemented and unit-tested, NOT YET WIRED into create_app() —
BLOCKED-TEST-CONFLICT F01-1 / F08-1 (docs/assessment/HUMAN_DECISIONS.md):
~70 existing API tests call the endpoints without credentials. Wiring is one
line per router (`dependencies=[Depends(require_api_key)]`) plus
config.validate_gateway_auth_config() in the lifespan.

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
    token = _bearer(websocket.headers.get("Authorization", "")) or websocket.query_params.get(
        "access_token", ""
    )
    origin = websocket.headers.get("Origin")
    origin_ok = origin is None or origin in get_cors_allowed_origins()
    if not token or not key_is_valid(token) or not origin_ok:
        await websocket.close(code=_WS_POLICY_VIOLATION)
        return False
    return True
