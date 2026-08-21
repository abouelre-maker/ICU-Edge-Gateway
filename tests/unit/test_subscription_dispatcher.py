"""
Unit Tests — infrastructure.streaming.subscription_dispatcher.SubscriptionDispatcher.

Uses httpx.MockTransport (real httpx request/response machinery, zero real
network I/O) rather than mocking SubscriptionDispatcher's own internals, so
these tests exercise the actual header-building/POST/status-code-handling
code path, not a stand-in for it.
"""

from __future__ import annotations

import asyncio

import httpx
from infrastructure.fhir.subscription import (
    Subscription,
    SubscriptionChannel,
    SubscriptionChannelType,
)
from infrastructure.streaming.subscription_dispatcher import (
    SubscriptionDispatcher,
    _parse_header_lines,
)
from infrastructure.streaming.subscription_registry import (
    MAX_CONSECUTIVE_DELIVERY_ERRORS,
    SubscriptionRegistry,
)


def _bundle(patient_id: str = "PT-001") -> dict:
    return {
        "resourceType": "Bundle",
        "entry": [{"resource": {"subject": {"reference": f"Patient/{patient_id}"}}}],
    }


def _subscription(sub_id: str = "sub-1", headers: tuple[str, ...] = ()) -> Subscription:
    return Subscription(
        id=sub_id,
        criteria="Bundle",
        channel=SubscriptionChannel(
            type=SubscriptionChannelType.REST_HOOK,
            endpoint="https://ehr.example.org/hook",
            headers=headers,
        ),
    )


async def _wait_until(predicate, timeout: float = 2.0, interval: float = 0.01) -> None:
    deadline = asyncio.get_event_loop().time() + timeout
    while asyncio.get_event_loop().time() < deadline:
        if predicate():
            return
        await asyncio.sleep(interval)
    raise AssertionError(f"Condition not met within {timeout}s")


class TestParseHeaderLines:
    def test_parses_well_formed_headers(self) -> None:
        parsed = _parse_header_lines(("Authorization: Bearer abc", "X-Tenant: hosp-a"))
        assert parsed == {"Authorization": "Bearer abc", "X-Tenant": "hosp-a"}

    def test_skips_malformed_header_without_colon(self) -> None:
        parsed = _parse_header_lines(("not-a-header", "X-Ok: yes"))
        assert parsed == {"X-Ok": "yes"}

    def test_empty_headers_returns_empty_dict(self) -> None:
        assert _parse_header_lines(()) == {}


class TestSuccessfulDelivery:
    async def test_delivers_bundle_and_records_success(self) -> None:
        received: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            received.append(request)
            return httpx.Response(200, json={"ok": True})

        registry = SubscriptionRegistry()
        sub = registry.create(_subscription(headers=("Authorization: Bearer tok",)))
        dispatcher = SubscriptionDispatcher(
            registry=registry,
            http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
        )

        matched = await dispatcher.dispatch(_bundle("PT-001"))
        assert matched == 1
        await _wait_until(lambda: len(received) == 1)

        request = received[0]
        assert request.headers["authorization"] == "Bearer tok"
        assert request.headers["content-type"] == "application/fhir+json"
        assert request.headers["x-cds-advisory-only"] == "true"
        assert sub.consecutive_delivery_errors == 0

        await dispatcher.aclose()

    async def test_no_matching_subscription_delivers_nothing(self) -> None:
        calls = 0

        def handler(request: httpx.Request) -> httpx.Response:
            nonlocal calls
            calls += 1
            return httpx.Response(200)

        registry = SubscriptionRegistry()  # nothing registered
        dispatcher = SubscriptionDispatcher(
            registry=registry,
            http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
        )

        matched = await dispatcher.dispatch(_bundle())
        assert matched == 0
        await asyncio.sleep(0.05)
        assert calls == 0
        await dispatcher.aclose()


class TestFailedDelivery:
    async def test_http_error_status_records_failure_not_success(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(503)

        registry = SubscriptionRegistry()
        sub = registry.create(_subscription())
        dispatcher = SubscriptionDispatcher(
            registry=registry,
            http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
        )

        await dispatcher.dispatch(_bundle("PT-001"))
        await _wait_until(lambda: sub.consecutive_delivery_errors == 1)
        assert sub.last_error is not None and "503" in sub.last_error

        await dispatcher.aclose()

    async def test_connection_error_records_failure(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("connection refused", request=request)

        registry = SubscriptionRegistry()
        sub = registry.create(_subscription())
        dispatcher = SubscriptionDispatcher(
            registry=registry,
            http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
        )

        await dispatcher.dispatch(_bundle("PT-001"))
        await _wait_until(lambda: sub.consecutive_delivery_errors == 1)

        await dispatcher.aclose()


class TestHazardDsp007NonFiniteBundleNeverDelivered:
    """
    ISO 14971 HAZARD-DSP-007 defense-in-depth: json.dumps(bundle,
    allow_nan=False) in _deliver() must raise on a non-finite value BEFORE
    the network call, recording a delivery failure (so the subscription's
    consecutive-error tracking still sees it) without ever POSTing a
    corrupted payload to the subscriber's endpoint.
    """

    def _bundle_with_nan_value(self, patient_id: str = "PT-NAN-001") -> dict:
        bundle = _bundle(patient_id)
        bundle["entry"][0]["resource"]["valueQuantity"] = {
            "value": float("nan"),
            "unit": "%",
        }
        return bundle

    async def test_non_finite_bundle_is_never_posted_to_subscriber(self) -> None:
        received: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            received.append(request)
            return httpx.Response(200)

        registry = SubscriptionRegistry()
        sub = registry.create(_subscription())
        dispatcher = SubscriptionDispatcher(
            registry=registry,
            http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
        )

        await dispatcher.dispatch(self._bundle_with_nan_value())
        await _wait_until(lambda: sub.consecutive_delivery_errors == 1)

        assert received == [], (
            "A bundle containing NaN must never reach the subscriber's "
            "endpoint -- json.dumps(allow_nan=False) must raise before the "
            "POST is attempted."
        )
        assert sub.last_error is not None and "not JSON-serializable" in sub.last_error

        await dispatcher.aclose()

    async def test_no_redelivery_after_failure_hazard_stream_008(self) -> None:
        """
        HAZARD-STREAM-008: a failed delivery is attempted once and NOT
        retried/requeued -- unlike the MQTT publisher's requeue-on-failure.
        """
        attempts = 0

        def handler(request: httpx.Request) -> httpx.Response:
            nonlocal attempts
            attempts += 1
            return httpx.Response(500)

        registry = SubscriptionRegistry()
        sub = registry.create(_subscription())
        dispatcher = SubscriptionDispatcher(
            registry=registry,
            http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
        )

        await dispatcher.dispatch(_bundle("PT-001"))
        await _wait_until(lambda: sub.consecutive_delivery_errors == 1)
        await asyncio.sleep(0.1)  # give any (incorrect) retry a chance to fire
        assert attempts == 1

        await dispatcher.aclose()

    async def test_repeated_failures_deactivate_subscription(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(500)

        registry = SubscriptionRegistry()
        sub = registry.create(_subscription())
        dispatcher = SubscriptionDispatcher(
            registry=registry,
            http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
        )

        for _ in range(MAX_CONSECUTIVE_DELIVERY_ERRORS):
            await dispatcher.dispatch(_bundle("PT-001"))
            await asyncio.sleep(0.02)

        from infrastructure.fhir.subscription import SubscriptionStatus

        assert sub.status is SubscriptionStatus.ERROR
        # Once errored, match() (called inside dispatch) no longer returns
        # it -- confirm no further attempts are even scheduled.
        matched = await dispatcher.dispatch(_bundle("PT-001"))
        assert matched == 0

        await dispatcher.aclose()
