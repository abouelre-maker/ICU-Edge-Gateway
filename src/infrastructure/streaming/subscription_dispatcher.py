"""
SubscriptionDispatcher — FHIR R4 Subscription rest-hook Delivery.

Phase 5 Section A. For every Bundle produced by any ingestion path (MLLP,
POST /api/v1/ingest, POST /api/v1/vitals), asks the SubscriptionRegistry
which registered Subscriptions care about it, then POSTs the Bundle to
each matching subscription's channel.endpoint.

SOUP (IEC 62304 §8.1.2): httpx==0.25.2. Already present in this repo as a
requirements-dev.txt test-only dependency; promoted here to a production
runtime dependency (requirements.txt) because Subscription delivery needs
an async HTTP client. Vetting note (2026-08-09): Endor Labs automated SCA
review is still unavailable in this environment (see the paho-mqtt vetting
note in mqtt_publisher.py for the same constraint). Manual web research:
the one httpx CVE found (CVE-2021-41945, an SSRF-adjacent input-validation
issue in httpx.URL.copy_with) was fixed in 0.23.0; this repo's pinned
0.25.2 is unaffected. A newer patch (0.28.1, as of this note) exists
upstream but is NOT adopted here -- httpx 0.25.2 is already exercised by
this repo's entire existing test suite via tests/conftest.py's ASGI test
client, and bumping it is a separate, independently-reviewable change, not
bundled into this Subscription feature. This is a WEB-SOURCED, NOT
ENDOR-VERIFIED SOUP determination -- flagged for human re-verification
before production sign-off, same as paho-mqtt.

Design mirrors mqtt_publisher.py/live_dashboard_channel.py: delivery to one
subscriber must never block delivery to another, and must never block the
caller that produced the Bundle. Each matching subscription's delivery
runs as an independent fire-and-forget asyncio task.

ISO 14971 HAZARD-STREAM-006 (existing, see infrastructure/streaming/
url_safety.py): endpoint SSRF baseline guard is enforced at registration
time, not here -- this module trusts that any Subscription in the registry
already passed validate_webhook_endpoint().

ISO 14971 HAZARD-STREAM-008 (PROPOSED — pending human risk-management
sign-off; new hazard for new code):
  Unlike the MQTT publisher (which requeues undelivered telemetry
  indefinitely, because that data must not be lost -- HAZARD-STREAM-003),
  a failed Subscription delivery is NOT retried or requeued: it is
  attempted once per occurrence, and only the subscription's consecutive-
  failure COUNT is updated (see subscription_registry.py). A subscriber
  that is briefly unreachable simply misses that Bundle -- there is no
  store-and-forward for Subscription deliveries. This mirrors the FHIR R4
  Subscription model (a live notification stream, not a guaranteed-
  delivery queue) but is a deliberate, not accidental, scope choice, and
  is flagged for human review: a clinical integration that requires
  guaranteed delivery should use the MQTT/MLLP store-and-forward path
  instead of a Subscription, or this dispatcher would need its own
  ring-buffer-backed retry queue (not implemented here).
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

import httpx
import structlog

from infrastructure.fhir.subscription import Subscription
from infrastructure.streaming.subscription_registry import SubscriptionRegistry

_log: structlog.BoundLogger = structlog.get_logger(__name__)

_DEFAULT_DELIVERY_TIMEOUT_SECONDS = 10.0


def _parse_header_lines(headers: tuple[str, ...]) -> dict[str, str]:
    """
    Parse FHIR R4 Subscription.channel.header entries ("Name: value"
    strings, per the spec) into a dict for httpx. Malformed entries
    (no ':') are skipped and logged rather than raising -- a delivery
    attempt should not be aborted by one bad header the subscriber
    themselves configured; that was already validated as best-effort at
    registration time.
    """
    parsed: dict[str, str] = {}
    for line in headers:
        if ":" not in line:
            _log.warning("subscription_dispatcher.malformed_header_skipped", line=line)
            continue
        name, _, value = line.partition(":")
        parsed[name.strip()] = value.strip()
    return parsed


class SubscriptionDispatcher:
    """
    Matches and delivers Bundles to registered FHIR R4 Subscriptions.

    Holds one shared httpx.AsyncClient for connection pooling across all
    deliveries; call aclose() during ASGI shutdown.
    """

    def __init__(
        self,
        registry: SubscriptionRegistry,
        timeout_seconds: float = _DEFAULT_DELIVERY_TIMEOUT_SECONDS,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        self._registry = registry
        self._timeout_seconds = timeout_seconds
        # Redirects are NOT followed by default (httpx's own default) --
        # deliberate: following a redirect would deliver clinical data to
        # an endpoint that was never registered/validated (HAZARD-STREAM-006).
        self._client = http_client or httpx.AsyncClient(timeout=timeout_seconds)

    async def dispatch(self, bundle: dict[str, Any]) -> int:
        """
        Match `bundle` against the registry and schedule delivery to every
        matching subscription. Returns the number of subscriptions matched
        (deliveries are fire-and-forget, so this is not a delivery-success
        count).
        """
        matches = self._registry.match(bundle)
        for sub in matches:
            asyncio.ensure_future(self._deliver(sub, bundle))
        return len(matches)

    def schedule_dispatch(self, bundle: dict[str, Any]) -> None:
        """
        Fire-and-forget variant of dispatch() for synchronous callers
        (MLLPListener._process_frame()) — mirrors
        LiveDashboardChannel.schedule_broadcast().
        """
        asyncio.ensure_future(self.dispatch(bundle))

    async def aclose(self) -> None:
        await self._client.aclose()

    async def _deliver(
        self, subscription: Subscription, bundle: dict[str, Any]
    ) -> None:
        headers = _parse_header_lines(subscription.channel.headers)
        headers["Content-Type"] = subscription.channel.payload_mime_type
        headers.setdefault("X-CDS-Advisory-Only", "true")

        log = _log.bind(
            subscription_id=subscription.id, endpoint=subscription.channel.endpoint
        )
        try:
            response = await self._client.post(
                subscription.channel.endpoint,
                content=json.dumps(bundle),
                headers=headers,
                timeout=self._timeout_seconds,
            )
            if response.status_code >= 400:
                error = f"HTTP {response.status_code} from subscriber endpoint"
                self._registry.record_delivery_failure(subscription.id, error)
                log.warning("subscription_dispatcher.delivery_rejected", error=error)
                return
        except httpx.HTTPError as exc:
            error = f"{type(exc).__name__}: {exc}"
            self._registry.record_delivery_failure(subscription.id, error)
            log.warning("subscription_dispatcher.delivery_failed", error=error)
            return

        self._registry.record_delivery_success(subscription.id)
        log.info("subscription_dispatcher.delivered", status_code=response.status_code)
