"""
Unit Tests — infrastructure.streaming.subscription_registry.SubscriptionRegistry.

Covers CRUD, criteria matching (all-patients vs patient-scoped), lazy
expiry, and the consecutive-delivery-error -> status=error transition
(subscription_dispatcher.py's HAZARD-STREAM-008 companion mechanism).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from infrastructure.fhir.subscription import (
    Subscription,
    SubscriptionChannel,
    SubscriptionChannelType,
    SubscriptionStatus,
)
from infrastructure.streaming.subscription_registry import (
    MAX_CONSECUTIVE_DELIVERY_ERRORS,
    SubscriptionRegistry,
)


def _bundle(patient_id: str = "PT-001") -> dict:
    return {
        "entry": [{"resource": {"subject": {"reference": f"Patient/{patient_id}"}}}]
    }


def _subscription(
    criteria: str = "Bundle",
    end: datetime | None = None,
) -> Subscription:
    return Subscription(
        id="sub-1",
        criteria=criteria,
        channel=SubscriptionChannel(
            type=SubscriptionChannelType.REST_HOOK,
            endpoint="https://ehr.example.org/hook",
        ),
        end=end,
    )


class TestCreateGetDelete:
    def test_create_sets_status_active(self) -> None:
        registry = SubscriptionRegistry()
        sub = registry.create(_subscription())
        assert sub.status is SubscriptionStatus.ACTIVE
        assert registry.get(sub.id) is sub

    def test_get_unknown_id_returns_none(self) -> None:
        registry = SubscriptionRegistry()
        assert registry.get("nonexistent") is None

    def test_delete_existing_returns_true(self) -> None:
        registry = SubscriptionRegistry()
        sub = registry.create(_subscription())
        assert registry.delete(sub.id) is True
        assert registry.get(sub.id) is None

    def test_delete_unknown_returns_false(self) -> None:
        registry = SubscriptionRegistry()
        assert registry.delete("nonexistent") is False

    def test_list_all_and_count(self) -> None:
        registry = SubscriptionRegistry()
        registry.create(
            Subscription(id="a", criteria="Bundle", channel=_subscription().channel)
        )
        registry.create(
            Subscription(id="b", criteria="Bundle", channel=_subscription().channel)
        )
        assert registry.count == 2
        assert {s.id for s in registry.list_all()} == {"a", "b"}


class TestMatchAllPatients:
    def test_bare_bundle_criteria_matches_any_patient(self) -> None:
        registry = SubscriptionRegistry()
        registry.create(_subscription(criteria="Bundle"))
        assert len(registry.match(_bundle("PT-001"))) == 1
        assert len(registry.match(_bundle("PT-999"))) == 1

    def test_no_subscriptions_matches_nothing(self) -> None:
        registry = SubscriptionRegistry()
        assert registry.match(_bundle()) == []


class TestMatchPatientScoped:
    def test_matches_only_the_configured_patient(self) -> None:
        registry = SubscriptionRegistry()
        sub = registry.create(_subscription(criteria="Bundle?patient=Patient/PT-042"))
        assert registry.match(_bundle("PT-042")) == [sub]
        assert registry.match(_bundle("PT-999")) == []


class TestMatchExcludesInactiveAndExpired:
    def test_off_status_does_not_match(self) -> None:
        registry = SubscriptionRegistry()
        sub = registry.create(_subscription())
        sub.status = SubscriptionStatus.OFF
        assert registry.match(_bundle()) == []

    def test_error_status_does_not_match(self) -> None:
        registry = SubscriptionRegistry()
        sub = registry.create(_subscription())
        sub.status = SubscriptionStatus.ERROR
        assert registry.match(_bundle()) == []

    def test_expired_subscription_is_excluded_and_transitioned_to_off(self) -> None:
        registry = SubscriptionRegistry()
        past = datetime.now(tz=timezone.utc) - timedelta(hours=1)
        sub = registry.create(_subscription(end=past))
        assert registry.match(_bundle()) == []
        assert sub.status is SubscriptionStatus.OFF

    def test_future_end_still_matches(self) -> None:
        registry = SubscriptionRegistry()
        future = datetime.now(tz=timezone.utc) + timedelta(hours=1)
        sub = registry.create(_subscription(end=future))
        assert registry.match(_bundle()) == [sub]


class TestDeliveryErrorAccounting:
    def test_success_resets_error_count(self) -> None:
        registry = SubscriptionRegistry()
        sub = registry.create(_subscription())
        sub.consecutive_delivery_errors = 3
        registry.record_delivery_success(sub.id)
        assert sub.consecutive_delivery_errors == 0

    def test_failures_below_threshold_stay_active(self) -> None:
        registry = SubscriptionRegistry()
        sub = registry.create(_subscription())
        for _ in range(MAX_CONSECUTIVE_DELIVERY_ERRORS - 1):
            registry.record_delivery_failure(sub.id, "connection refused")
        assert sub.status is SubscriptionStatus.ACTIVE
        assert sub.consecutive_delivery_errors == MAX_CONSECUTIVE_DELIVERY_ERRORS - 1

    def test_reaching_threshold_transitions_to_error(self) -> None:
        registry = SubscriptionRegistry()
        sub = registry.create(_subscription())
        for _ in range(MAX_CONSECUTIVE_DELIVERY_ERRORS):
            registry.record_delivery_failure(sub.id, "connection refused")
        assert sub.status is SubscriptionStatus.ERROR
        assert sub.last_error == "connection refused"

    def test_errored_subscription_stops_matching(self) -> None:
        registry = SubscriptionRegistry()
        sub = registry.create(_subscription())
        for _ in range(MAX_CONSECUTIVE_DELIVERY_ERRORS):
            registry.record_delivery_failure(sub.id, "timeout")
        assert registry.match(_bundle()) == []

    def test_recording_against_unknown_id_is_a_no_op(self) -> None:
        registry = SubscriptionRegistry()
        registry.record_delivery_failure("nonexistent", "irrelevant")
        registry.record_delivery_success("nonexistent")  # must not raise
