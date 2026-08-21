"""
Integration Tests — Global Unhandled-Exception Handler (REQ-API-002).

REQ-API-002 (src/main.py:248): any unhandled exception reaching the ASGI
app SHALL be logged server-side at ERROR level and returned to the caller
as a generic HTTP 500 — with NO exception type, message, or traceback
exposed in the response body.

This is the dedicated regression test flagged as missing in SRS-001 §6 and
RMF-001 (REQ-API-002 entry): `test_api_ingest.py::test_error_response_has_detail_field`
accepts either a 422 or 500 and only checks a `detail` key exists — it does
not exercise the catch-all handler specifically, and does not assert
non-leakage of exception internals. This file closes that gap directly
against `unhandled_exception_handler` (src/main.py:240-267), independent of
any one endpoint's internal implementation.

Uses `ASGITransport(..., raise_app_exceptions=False)`: Starlette's
`ServerErrorMiddleware` sends the handler's 500 response to the client AND
re-raises the original exception afterward (so a real ASGI server's own
process-level logging still sees it) — httpx's default
`raise_app_exceptions=True` would propagate that re-raise into the test as
a raised exception instead of a response object. Disabling it here mirrors
what an actual deployed client receives: only the 500 response, never the
exception.
"""

from __future__ import annotations

import pytest
import structlog.testing
from httpx import ASGITransport, AsyncClient
from main import create_app

# A deliberately sensitive-looking message: if this string (or the
# exception's type name) ever appears in the HTTP response, the handler is
# leaking implementation/internal detail to an external caller.
_SECRET_DETAIL = "db_password=hunter2 at /etc/icu-gateway/secrets.conf line 42"


def _install_boom_route(app: object) -> None:
    """Attach a route that always raises an unhandled, non-ValueError exception.

    Deliberately NOT a ValueError — that path is already covered by
    `value_error_handler`/REQ-API-001. This isolates the catch-all
    `Exception` handler (REQ-API-002) specifically.
    """

    @app.get("/__test_unhandled_exception__")  # type: ignore[attr-defined]
    async def _boom() -> None:
        raise RuntimeError(_SECRET_DETAIL)


@pytest.mark.integration
class TestReqApi002NoLeakOnUnhandledException:
    async def test_response_body_omits_exception_type_message_and_traceback(
        self,
    ) -> None:
        app = create_app()
        _install_boom_route(app)

        async with AsyncClient(
            transport=ASGITransport(app=app, raise_app_exceptions=False),
            base_url="http://test",
        ) as client:
            response = await client.get("/__test_unhandled_exception__")

        assert response.status_code == 500

        raw_text = response.text
        assert "RuntimeError" not in raw_text
        assert _SECRET_DETAIL not in raw_text
        assert "hunter2" not in raw_text
        assert "secrets.conf" not in raw_text
        assert "Traceback" not in raw_text
        assert "File \"" not in raw_text  # Python traceback frame marker

        body = response.json()
        assert body == {
            "error": "internal_server_error",
            "detail": (
                "An unexpected error occurred. "
                "Consult the gateway logs for details."
            ),
        }

    async def test_response_headers_omit_exception_detail(self) -> None:
        app = create_app()
        _install_boom_route(app)

        async with AsyncClient(
            transport=ASGITransport(app=app, raise_app_exceptions=False),
            base_url="http://test",
        ) as client:
            response = await client.get("/__test_unhandled_exception__")

        header_blob = " ".join(f"{k}:{v}" for k, v in response.headers.items())
        assert "RuntimeError" not in header_blob
        assert _SECRET_DETAIL not in header_blob

    async def test_exception_is_still_logged_server_side_at_error_level(
        self,
    ) -> None:
        """
        Confirms the other half of REQ-API-002: non-leakage to the caller
        must NOT come at the cost of losing server-side observability. The
        exception type/message SHALL still reach the structured server log
        at ERROR level, even though it is withheld from the HTTP response.
        """
        app = create_app()
        _install_boom_route(app)

        with structlog.testing.capture_logs() as captured:
            async with AsyncClient(
                transport=ASGITransport(app=app, raise_app_exceptions=False),
                base_url="http://test",
            ) as client:
                response = await client.get("/__test_unhandled_exception__")

        assert response.status_code == 500

        error_events = [e for e in captured if e.get("log_level") == "error"]
        assert any(
            e.get("event") == "api.unhandled_exception"
            and e.get("exc_type") == "RuntimeError"
            and e.get("error") == _SECRET_DETAIL
            for e in error_events
        ), f"expected a structlog ERROR event carrying exc_type/error; got {captured!r}"
