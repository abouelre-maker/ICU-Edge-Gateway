"""
SubscriptionRegistry — In-Memory FHIR R4 Subscription Store and Matcher.

Phase 5 Section A. Holds every registered Subscription for this edge
gateway instance and matches produced Bundles against them. Delivery
itself (HTTP POST to channel.endpoint) lives in
infrastructure/streaming/subscription_dispatcher.py — this module only
answers "which subscriptions, if any, care about this Bundle".

SIMPLIFICATIONS (documented, not silently assumed away):
  - In-memory only. Subscriptions do not survive an appliance restart.
    A production deployment needing durable subscriptions across restarts
    would need a persistence layer -- out of scope for this pass, flagged
    as a follow-up rather than implemented as a stub.
  - No FHIR "handshake" notification. A conformant FHIR R4 subscription
    server typically sends a handshake notification to channel.endpoint
    before transitioning status from "requested" to "active", so the
    subscriber can confirm receipt. This gateway transitions straight to
    "active" once registration-time validation passes (see
    infrastructure/fhir/subscription.py) -- there is no handshake ping.
  - No reactivation path. Once a subscription's status becomes "error"
    (after MAX_CONSECUTIVE_DELIVERY_ERRORS consecutive delivery failures),
    it stops being matched/delivered to permanently; the only way back is
    for the subscriber to delete and re-create it. There is no PATCH/PUT
    endpoint to manually reactivate an errored subscription in this pass.

ISO 14971 HAZARD-STREAM-007 (PROPOSED — pending human risk-management
sign-off; new hazard for new code, not a resolution of an existing one):
  A Subscription whose criteria is accepted at registration time but never
  actually matches any Bundle (e.g. a patient_id that is misspelled, or a
  patient who is never actually monitored) would sit "active" forever
  while silently never firing -- indistinguishable, from the subscriber's
  point of view, from "no Bundles have occurred yet". This gateway
  mitigates the WORST version of this risk (criteria syntax this gateway
  can't evaluate at all) by rejecting unsupported criteria strings
  outright at registration time (infrastructure/fhir/subscription.py). It
  does NOT mitigate the milder version (syntactically supported criteria
  that simply never matches real data, e.g. a typo'd patient_id) -- there
  is no "this subscription has matched zero Bundles in N hours" alerting
  in this pass. Flagged for human review: a production deployment likely
  wants such an idle-subscription alert.
"""

from __future__ import annotations

import threading
from datetime import datetime, timezone

import structlog

from infrastructure.fhir.subscription import (
    Subscription,
    SubscriptionStatus,
    parse_patient_filter,
)
from infrastructure.streaming.fhir_bundle_utils import extract_patient_id

_log: structlog.BoundLogger = structlog.get_logger(__name__)

MAX_CONSECUTIVE_DELIVERY_ERRORS = 5


class SubscriptionRegistry:
    """Thread-safe in-memory store + Bundle-to-subscription matcher."""

    def __init__(self) -> None:
        self._subscriptions: dict[str, Subscription] = {}
        self._lock = threading.Lock()

    def create(self, subscription: Subscription) -> Subscription:
        subscription.status = SubscriptionStatus.ACTIVE
        with self._lock:
            self._subscriptions[subscription.id] = subscription
        _log.info(
            "subscription_registry.created",
            subscription_id=subscription.id,
            criteria=subscription.criteria,
        )
        return subscription

    def get(self, subscription_id: str) -> Subscription | None:
        with self._lock:
            return self._subscriptions.get(subscription_id)

    def delete(self, subscription_id: str) -> bool:
        with self._lock:
            existed = self._subscriptions.pop(subscription_id, None) is not None
        if existed:
            _log.info("subscription_registry.deleted", subscription_id=subscription_id)
        return existed

    def list_all(self) -> list[Subscription]:
        with self._lock:
            return list(self._subscriptions.values())

    @property
    def count(self) -> int:
        with self._lock:
            return len(self._subscriptions)

    def match(self, bundle: dict) -> list[Subscription]:
        """
        Return every currently-ACTIVE, non-expired subscription whose
        criteria matches `bundle`. Expired subscriptions encountered here
        are transitioned to status=off as a side effect (lazy expiry —
        there is no background sweep task in this pass).
        """
        now = datetime.now(tz=timezone.utc)
        matched: list[Subscription] = []
        with self._lock:
            candidates = list(self._subscriptions.values())

        for sub in candidates:
            if sub.status is not SubscriptionStatus.ACTIVE:
                continue
            if sub.end is not None and sub.end <= now:
                sub.status = SubscriptionStatus.OFF
                _log.info("subscription_registry.expired", subscription_id=sub.id)
                continue
            if self._criteria_matches(sub, bundle):
                matched.append(sub)
        return matched

    def record_delivery_success(self, subscription_id: str) -> None:
        sub = self.get(subscription_id)
        if sub is not None:
            sub.consecutive_delivery_errors = 0

    def record_delivery_failure(self, subscription_id: str, error: str) -> None:
        sub = self.get(subscription_id)
        if sub is None:
            return
        sub.consecutive_delivery_errors += 1
        sub.last_error = error
        if sub.consecutive_delivery_errors >= MAX_CONSECUTIVE_DELIVERY_ERRORS:
            sub.status = SubscriptionStatus.ERROR
            _log.warning(
                "subscription_registry.deactivated_after_repeated_errors",
                subscription_id=subscription_id,
                consecutive_errors=sub.consecutive_delivery_errors,
                last_error=error,
            )
        else:
            _log.warning(
                "subscription_registry.delivery_failed",
                subscription_id=subscription_id,
                consecutive_errors=sub.consecutive_delivery_errors,
                error=error,
            )

    @staticmethod
    def _criteria_matches(sub: Subscription, bundle: dict) -> bool:
        # parse_patient_filter() cannot raise here -- criteria was already
        # validated as supported at registration time (create_subscription_
        # from_fhir_request()).
        patient_filter = parse_patient_filter(sub.criteria)
        if patient_filter is None:
            return True
        return extract_patient_id(bundle) == patient_filter
