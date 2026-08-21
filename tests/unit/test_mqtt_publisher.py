"""
Unit Tests — MQTTPublisher (Phase 5 Section A edge->cloud publisher).

Uses a lightweight fake in place of paho.mqtt.client.Client instead of a
real broker connection — there is no MQTT broker available in this test
environment, and these tests target the publisher's own topic-routing,
ordering, and requeue-on-failure logic (HAZARD-STREAM-002/003), not
paho-mqtt's wire protocol (Eclipse-maintained SOUP, not re-verified here).
"""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import Callable
from typing import Any

import paho.mqtt.client as mqtt
import pytest
from infrastructure.streaming.mqtt_publisher import MQTTPublisher, _extract_patient_id
from infrastructure.streaming.ring_buffer import StoreAndForwardRingBuffer


def _bundle_for_patient(patient_id: str) -> dict[str, Any]:
    return {
        "resourceType": "Bundle",
        "entry": [
            {
                "resource": {
                    "resourceType": "Observation",
                    "subject": {"reference": f"Patient/{patient_id}"},
                }
            }
        ],
    }


class TestExtractPatientId:
    def test_extracts_patient_id_from_first_observation_subject(self) -> None:
        bundle = _bundle_for_patient("PT-001")
        assert _extract_patient_id(bundle) == "PT-001"

    def test_returns_unknown_for_bundle_with_no_entries(self) -> None:
        assert _extract_patient_id({"resourceType": "Bundle", "entry": []}) == "UNKNOWN"

    def test_returns_unknown_for_bundle_missing_entry_key(self) -> None:
        assert _extract_patient_id({}) == "UNKNOWN"

    def test_skips_non_patient_subject_references(self) -> None:
        bundle = {
            "entry": [
                {"resource": {"subject": {"reference": "Device/DEVICE-1"}}},
                {"resource": {"subject": {"reference": "Patient/PT-002"}}},
            ]
        }
        assert _extract_patient_id(bundle) == "PT-002"


class TestTopicFor:
    def test_builds_topic_from_prefix_and_patient_id(self) -> None:
        buf: StoreAndForwardRingBuffer[dict[str, Any]] = StoreAndForwardRingBuffer(
            capacity=10
        )
        pub = MQTTPublisher(
            buffer=buf, broker_host="127.0.0.1", topic_prefix="icu-edge/vitals"
        )
        assert pub.topic_for(_bundle_for_patient("PT-007")) == "icu-edge/vitals/PT-007"

    def test_strips_trailing_slash_from_configured_prefix(self) -> None:
        buf: StoreAndForwardRingBuffer[dict[str, Any]] = StoreAndForwardRingBuffer(
            capacity=10
        )
        pub = MQTTPublisher(
            buffer=buf, broker_host="127.0.0.1", topic_prefix="icu-edge/vitals/"
        )
        assert pub.topic_for(_bundle_for_patient("PT-007")) == "icu-edge/vitals/PT-007"


class TestConstructorValidation:
    def test_rejects_invalid_qos(self) -> None:
        buf: StoreAndForwardRingBuffer[dict[str, Any]] = StoreAndForwardRingBuffer(
            capacity=10
        )
        with pytest.raises(ValueError, match="qos must be 0, 1, or 2"):
            MQTTPublisher(buffer=buf, broker_host="127.0.0.1", qos=9)


class _FakePublishInfo:
    def __init__(self, rc: int) -> None:
        self.rc = rc

    def wait_for_publish(self, timeout: float) -> None:  # noqa: ARG002
        return None


class _FakeMQTTClient:
    """Minimal stand-in for paho.mqtt.client.Client's publish() surface."""

    def __init__(self, fail_on_topics: set[str] | None = None) -> None:
        self.published: list[tuple[str, str, int]] = []
        self._fail_on_topics = fail_on_topics or set()

    def publish(self, topic: str, payload: str, qos: int) -> _FakePublishInfo:
        if topic in self._fail_on_topics:
            return _FakePublishInfo(rc=mqtt.MQTT_ERR_NO_CONN)
        self.published.append((topic, payload, qos))
        return _FakePublishInfo(rc=mqtt.MQTT_ERR_SUCCESS)


def _publisher_with_fake_client(
    fail_on_topics: set[str] | None = None,
    **kwargs: Any,
) -> tuple[MQTTPublisher, StoreAndForwardRingBuffer[dict[str, Any]], _FakeMQTTClient]:
    buf: StoreAndForwardRingBuffer[dict[str, Any]] = StoreAndForwardRingBuffer(
        capacity=100
    )
    pub = MQTTPublisher(buffer=buf, broker_host="127.0.0.1", qos=1, **kwargs)
    fake = _FakeMQTTClient(fail_on_topics=fail_on_topics)
    pub._client = fake  # type: ignore[assignment]  # bypass start(); no real broker in tests
    return pub, buf, fake


class TestPublishBatchSync:
    def test_all_succeed_returns_empty_unpublished_list(self) -> None:
        pub, _, fake = _publisher_with_fake_client()
        batch = [_bundle_for_patient("PT-001"), _bundle_for_patient("PT-002")]

        unpublished = pub._publish_batch_sync(batch)

        assert unpublished == []
        assert len(fake.published) == 2

    def test_first_failure_stops_batch_and_returns_remainder_in_order(self) -> None:
        pub, _, fake = _publisher_with_fake_client(
            fail_on_topics={"icu-edge/vitals/PT-002"}
        )
        batch = [
            _bundle_for_patient("PT-001"),
            _bundle_for_patient("PT-002"),  # fails
            _bundle_for_patient("PT-003"),  # never attempted after the failure
        ]

        unpublished = pub._publish_batch_sync(batch)

        assert unpublished == [batch[1], batch[2]]
        assert len(fake.published) == 1  # only PT-001 made it through


class TestHazardDsp007NonFiniteBundleNeverPublished:
    """
    ISO 14971 HAZARD-DSP-007 defense-in-depth: json.dumps(bundle,
    allow_nan=False) in _publish_batch_sync must raise on a non-finite
    value, and that must be handled as a poison-pill (dropped, logged,
    NOT requeued, NOT blocking sibling items in the same batch) -- distinct
    from a network/broker failure, which DOES requeue and DOES block
    (see test_first_failure_stops_batch_and_returns_remainder_in_order
    above for that contrasting behavior).
    """

    def _bundle_with_nan_value(self, patient_id: str) -> dict[str, Any]:
        bundle = _bundle_for_patient(patient_id)
        bundle["entry"][0]["resource"]["valueQuantity"] = {
            "value": float("nan"),
            "unit": "%",
        }
        return bundle

    def test_non_finite_bundle_is_never_handed_to_the_mqtt_client(self) -> None:
        pub, _, fake = _publisher_with_fake_client()
        batch = [self._bundle_with_nan_value("PT-NAN-001")]

        pub._publish_batch_sync(batch)

        assert fake.published == [], (
            "A bundle containing NaN must never reach client.publish() -- "
            "json.dumps(allow_nan=False) must raise before that call."
        )

    def test_non_finite_bundle_is_dropped_not_requeued(self) -> None:
        """Retrying an unserializable bundle can never succeed -- it must
        NOT come back out in `unpublished` (that would requeue it forever)."""
        pub, _, fake = _publisher_with_fake_client()
        batch = [self._bundle_with_nan_value("PT-NAN-001")]

        unpublished = pub._publish_batch_sync(batch)

        assert unpublished == []
        assert fake.published == []

    def test_non_finite_bundle_does_not_block_sibling_bundles_in_the_batch(
        self,
    ) -> None:
        """The key behavioral difference from a broker/network failure:
        a poison-pill bundle must NOT set the batch's `failing` flag --
        every valid sibling bundle, before AND after it in the batch, must
        still be published."""
        pub, _, fake = _publisher_with_fake_client()
        batch = [
            _bundle_for_patient("PT-001"),
            self._bundle_with_nan_value("PT-NAN-001"),
            _bundle_for_patient("PT-003"),
        ]

        unpublished = pub._publish_batch_sync(batch)

        assert unpublished == []
        published_topics = {topic for topic, _, _ in fake.published}
        assert published_topics == {
            "icu-edge/vitals/PT-001",
            "icu-edge/vitals/PT-003",
        }


async def _wait_until(
    predicate: Callable[[], bool], timeout: float = 2.0, interval: float = 0.01
) -> None:
    """
    Poll `predicate` until it returns True or `timeout` elapses.

    Used instead of a single fixed `asyncio.sleep()` so these tests are not
    flaky under CI/system load, where a busy thread-pool executor can delay
    an in-flight run_in_executor() call well past a short fixed sleep.
    """
    deadline = asyncio.get_event_loop().time() + timeout
    while asyncio.get_event_loop().time() < deadline:
        if predicate():
            return
        await asyncio.sleep(interval)
    raise AssertionError(f"Condition not met within {timeout}s: {predicate}")


class TestRunLoopRequeueOnFailure:
    async def test_failed_item_is_requeued_not_dropped(self) -> None:
        pub, buf, _fake = _publisher_with_fake_client(
            fail_on_topics={"icu-edge/vitals/PT-999"},
            # A generous retry backoff means the buffer spends most of its
            # time settled (post-requeue) rather than mid-cycle, so sampling
            # it after the first cycle completes is not a race.
            publish_interval_seconds=0.05,
            retry_backoff_seconds=0.5,
            drain_batch_size=10,
        )
        buf.push(_bundle_for_patient("PT-999"))

        pub._stop_event = asyncio.Event()
        task = asyncio.ensure_future(pub._run_loop())
        try:
            # Wait for the first (failing) publish attempt to complete and
            # requeue the item, then confirm it lands back in the buffer —
            # never dropped — and is never miscounted as published.
            await _wait_until(lambda: pub.published_count == 0 and buf.size() == 1)
            await asyncio.sleep(0.05)  # settle within the backoff window
            assert buf.size() == 1
            assert pub.published_count == 0
        finally:
            pub._stop_event.set()
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task

    async def test_successful_publish_drains_buffer_and_counts(self) -> None:
        pub, buf, fake = _publisher_with_fake_client(
            publish_interval_seconds=0.5,  # idle-poll interval; irrelevant here
            drain_batch_size=10,
        )
        buf.push(_bundle_for_patient("PT-001"))
        buf.push(_bundle_for_patient("PT-002"))

        pub._stop_event = asyncio.Event()
        task = asyncio.ensure_future(pub._run_loop())
        try:
            await _wait_until(lambda: pub.published_count == 2)
            assert buf.size() == 0
            assert len(fake.published) == 2
        finally:
            pub._stop_event.set()
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task
