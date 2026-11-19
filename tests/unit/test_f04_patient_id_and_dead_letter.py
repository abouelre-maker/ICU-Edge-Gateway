"""
F-04 — a patient_id containing MQTT topic characters must not halt telemetry.

- /vitals validates patient_id against ^[A-Za-z0-9._-]{1,64}$ (422 otherwise).
- The HL7 adapter reports such an identifier (AMBIGUOUS_PATIENT_ID ⇒ no score).
- The MQTT publisher dead-letters a message whose topic cannot be built or is
  rejected by paho (ValueError) instead of requeuing it forever at the head
  of the queue; the rest of the batch keeps draining.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import paho.mqtt.client as mqtt
import pytest
from domain.entities.score_outcome import ReasonCode
from httpx import AsyncClient
from infrastructure.adapters.hl7v2_adapter import HL7v2Adapter
from infrastructure.streaming.mqtt_publisher import MQTTPublisher
from infrastructure.streaming.ring_buffer import StoreAndForwardRingBuffer


def _payload(pid: str) -> dict[str, object]:
    return {
        "patient_id": pid,
        "samples": [
            {
                "vital_sign_type": "HEART_RATE", "value": 72, "unit": "bpm",
                "timestamp": datetime.now(tz=timezone.utc).isoformat(),
            }
        ],
    }


@pytest.mark.parametrize("pid", ["a/b", "a+b#c", "x" * 65, "has space", ""])
async def test_vitals_rejects_topic_unsafe_patient_id(client: AsyncClient, pid: str) -> None:
    resp = await client.post("/api/v1/vitals", json=_payload(pid))
    assert resp.status_code == 422


async def test_vitals_accepts_safe_patient_id(client: AsyncClient) -> None:
    resp = await client.post("/api/v1/vitals", json=_payload("PT-001.x_y"))
    assert resp.status_code == 200


def test_hl7_unsafe_patient_id_is_reported() -> None:
    msg = (
        "MSH|^~\\&|MON|ICU|EHR|HOSP|20260929110000||ORU^R01|C1|P|2.5.1\r"
        "PID|1||a/b+c#d^^^H^MR\r"
        "OBX|1|NM|8867-4^HR^LN||72|/min|||||F"
    )
    res = HL7v2Adapter().parse(msg)
    assert ReasonCode.AMBIGUOUS_PATIENT_ID in [f.code for f in res.findings]


def _bundle(pid: str) -> dict[str, Any]:
    return {
        "resourceType": "Bundle",
        "entry": [
            {"resource": {"resourceType": "Observation", "subject": {"reference": f"Patient/{pid}"}}}
        ],
    }


class _Info:
    rc = mqtt.MQTT_ERR_SUCCESS

    def wait_for_publish(self, timeout: float) -> None:  # noqa: ARG002
        return None


class _Client:
    def __init__(self, raise_value_error_on: str | None = None) -> None:
        self.published: list[str] = []
        self._bad = raise_value_error_on

    def publish(self, topic: str, payload: str, qos: int) -> _Info:  # noqa: ARG002
        if self._bad and self._bad in topic:
            raise ValueError("Publish topic cannot contain wildcards.")
        self.published.append(topic)
        return _Info()


def _pub(client: _Client) -> MQTTPublisher:
    buf: StoreAndForwardRingBuffer[dict[str, Any]] = StoreAndForwardRingBuffer(capacity=10)
    pub = MQTTPublisher(buffer=buf, broker_host="127.0.0.1", qos=1)
    pub._client = client  # type: ignore[assignment]
    return pub


def test_unsafe_patient_id_is_dead_lettered_not_requeued() -> None:
    client = _Client()
    pub = _pub(client)
    unpublished = pub._publish_batch_sync([_bundle("a+b#c"), _bundle("PT-OK")])
    assert unpublished == []  # nothing requeued → queue keeps draining
    assert client.published == ["icu-edge/vitals/PT-OK"]
    assert pub.dead_letter_count == 1


def test_paho_value_error_is_dead_lettered_not_requeued() -> None:
    client = _Client(raise_value_error_on="PT-BAD")
    pub = _pub(client)
    unpublished = pub._publish_batch_sync([_bundle("PT-BAD"), _bundle("PT-OK")])
    assert unpublished == []
    assert client.published == ["icu-edge/vitals/PT-OK"]
    assert pub.dead_letter_count == 1
