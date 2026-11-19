"""F-04 / F04-1: MQTT topics never carry the patient identifier."""

from __future__ import annotations

from typing import Any

import pytest
from config import get_mqtt_topic_key
from infrastructure.streaming.mqtt_publisher import MQTTPublisher, opaque_topic_segment
from infrastructure.streaming.ring_buffer import StoreAndForwardRingBuffer

_KEY = b"k" * 40


def _bundle(pid: str) -> dict[str, Any]:
    return {
        "resourceType": "Bundle",
        "entry": [
            {"resource": {"resourceType": "Observation", "subject": {"reference": f"Patient/{pid}"}}}
        ],
    }


def _pub(key: bytes | None) -> MQTTPublisher:
    return MQTTPublisher(
        buffer=StoreAndForwardRingBuffer(capacity=4), broker_host="127.0.0.1", topic_key=key
    )


def test_segment_is_stable_for_one_key() -> None:
    assert opaque_topic_segment("MRN-123", _KEY) == opaque_topic_segment("MRN-123", _KEY)


def test_segment_differs_per_patient_and_per_key() -> None:
    assert opaque_topic_segment("MRN-123", _KEY) != opaque_topic_segment("MRN-124", _KEY)
    assert opaque_topic_segment("MRN-123", _KEY) != opaque_topic_segment("MRN-123", b"j" * 40)


def test_segment_is_128_bit_hex_and_topic_safe() -> None:
    seg = opaque_topic_segment("MRN-123", _KEY)
    assert len(seg) == 32
    assert all(c in "0123456789abcdef" for c in seg)


def test_topic_never_contains_identifier() -> None:
    topic = _pub(_KEY).topic_for(_bundle("MRN-0042"))
    assert "MRN-0042" not in topic and "0042" not in topic
    assert topic.startswith("icu-edge/vitals/")


def test_without_configured_key_topics_are_still_opaque() -> None:
    topic = _pub(None).topic_for(_bundle("MRN-0042"))
    assert "MRN-0042" not in topic


def test_unset_topic_key_refuses(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("MQTT_TOPIC_KEY", raising=False)
    with pytest.raises(RuntimeError, match="MQTT_TOPIC_KEY"):
        get_mqtt_topic_key()


def test_short_topic_key_refuses(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MQTT_TOPIC_KEY", "short")
    with pytest.raises(RuntimeError, match="MQTT_TOPIC_KEY"):
        get_mqtt_topic_key()


def test_valid_topic_key_is_returned(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MQTT_TOPIC_KEY", "t" * 32)
    assert get_mqtt_topic_key() == b"t" * 32
