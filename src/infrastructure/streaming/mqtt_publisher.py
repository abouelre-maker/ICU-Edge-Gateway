"""
MQTTPublisher — Edge->Cloud Vitals Telemetry Publisher.

Phase 5 Section A follow-up. Drains a StoreAndForwardRingBuffer of FHIR R4
Bundle telemetry (populated by MLLPListener, or any other source pushing
onto the same buffer) and publishes each Bundle as an MQTT PUBLISH message
to a cloud broker, one topic per patient. This module changes no DSP, NEWS2,
FHIR assembly, or MLLP framing behavior — it only forwards already-assembled
Bundles.

SOUP (IEC 62304 §8.1.2): paho-mqtt==2.1.0 (Eclipse Foundation). Vetting note
(2026-08-09): the Endor Labs dependency-reviewer agent could not run in this
environment (no endorctl / namespace configured) and returned a
evidence-limited NOT_RECOMMENDED — not a finding against the package, an
absence of automated evidence. Manual web research found no CVEs against the
Python client (the one 2025 Paho CVE, CVE-2025-10543, is specific to the Go
client, paho.mqtt.golang); the project is an actively maintained Eclipse
Foundation project, EPL/EDL dual-licensed. This is a WEB-SOURCED, NOT
ENDOR-VERIFIED SOUP determination and should be re-verified against Endor
(or an equivalent SCA tool) before production sign-off — flagged for human
review, per session decision.

ISO 14971 HAZARD-STREAM-003 (PROPOSED — pending human risk-management
sign-off; new hazard for new code):
  The cloud MQTT broker may be unreachable (WAN outage, broker down, auth
  failure) for an extended period. A publisher that raises/crashes on
  connection failure would take down the edge appliance's ingestion path
  with it; a publisher that silently drops undelivered telemetry on failure
  would lose clinical data with no record.
  Mitigation implemented here:
    - Uses paho-mqtt's connect_async() + loop_start() + reconnect_delay_set()
      so connection loss triggers the library's own bounded-backoff
      reconnect loop rather than an unhandled exception.
    - A drained batch that fails partway through publishing is returned,
      in full from the first failure onward (never partially re-queued out
      of order), to StoreAndForwardRingBuffer.requeue_front() — so
      undelivered telemetry is retried, not discarded, subject to that
      buffer's own bounded-capacity/drop-oldest overflow policy
      (HAZARD-STREAM-002), which still applies here.
    - Default QoS is 1 (at-least-once) with wait_for_publish(), so a
      "success" is a broker PUBACK, not merely a local enqueue.
  NOT mitigated here: end-to-end (edge-to-cloud-consumer) delivery
  confirmation — QoS 1 confirms broker receipt, not that a downstream
  subscriber processed the message. That is a broader distributed-systems
  guarantee outside a single edge publisher's control.

ISO 14971 HAZARD-STREAM-004 (PROPOSED — pending human risk-management
sign-off; new hazard for new code):
  MQTT_USE_TLS can be disabled (see config.get_mqtt_config()). Publishing
  clinical telemetry over a WAN link without TLS is a confidentiality and
  integrity hazard. Mitigation implemented here: TLS defaults to enabled;
  disabling it is possible (for local-network development against a test
  broker) but logs a WARNING at connect time naming the risk explicitly,
  so a misconfiguration is visible in the edge appliance's audit trail
  rather than silent.
"""

from __future__ import annotations

import asyncio
import contextlib
import functools
import json
from typing import Any

import paho.mqtt.client as mqtt
import structlog

from infrastructure.streaming.ring_buffer import StoreAndForwardRingBuffer

_log: structlog.BoundLogger = structlog.get_logger(__name__)

_DEFAULT_RETRY_BACKOFF_SECONDS = 5.0
_DEFAULT_PUBLISH_TIMEOUT_SECONDS = 10.0
_DEFAULT_MIN_RECONNECT_DELAY_SECONDS = 1
_DEFAULT_MAX_RECONNECT_DELAY_SECONDS = 60


def _extract_patient_id(bundle: dict[str, Any]) -> str:
    """
    Best-effort extraction of the FHIR Patient logical ID from a Bundle, for
    MQTT topic routing. Every Observation entry carries
    `subject: {"reference": "Patient/{id}"}` (see observation_builder.py) —
    the first one found is authoritative, since all entries in one Bundle
    share the same subject. Falls back to "UNKNOWN" for an empty/malformed
    Bundle rather than raising — a publish/topic-routing failure must never
    be allowed to drop telemetry that already passed the domain pipeline.
    """
    for entry in bundle.get("entry", []):
        resource = entry.get("resource", {})
        reference = resource.get("subject", {}).get("reference", "")
        if reference.startswith("Patient/"):
            return reference.removeprefix("Patient/")
    return "UNKNOWN"


class MQTTPublisher:
    """
    Background asyncio-managed MQTT publisher over paho-mqtt's sync client.

    paho-mqtt is callback/thread-driven, not asyncio-native: connection
    management runs on paho's own network thread (loop_start()), and this
    class's polling loop drains the buffer and offloads blocking publish
    calls to a thread-pool executor so the asyncio event loop is never
    blocked (consistent with the rest of this codebase's async design).
    """

    def __init__(
        self,
        buffer: StoreAndForwardRingBuffer[dict[str, Any]],
        broker_host: str,
        broker_port: int = 8883,
        topic_prefix: str = "icu-edge/vitals",
        client_id: str = "icu-edge-gateway",
        use_tls: bool = True,
        qos: int = 1,
        username: str | None = None,
        password: str | None = None,
        publish_interval_seconds: float = 1.0,
        drain_batch_size: int = 50,
        retry_backoff_seconds: float = _DEFAULT_RETRY_BACKOFF_SECONDS,
        publish_timeout_seconds: float = _DEFAULT_PUBLISH_TIMEOUT_SECONDS,
    ) -> None:
        if qos not in (0, 1, 2):
            raise ValueError(f"qos must be 0, 1, or 2 per the MQTT spec. Got {qos!r}.")

        self._buffer = buffer
        self._broker_host = broker_host
        self._broker_port = broker_port
        self._topic_prefix = topic_prefix.rstrip("/")
        self._client_id = client_id
        self._use_tls = use_tls
        self._qos = qos
        self._username = username
        self._password = password
        self._publish_interval_seconds = publish_interval_seconds
        self._drain_batch_size = drain_batch_size
        self._retry_backoff_seconds = retry_backoff_seconds
        self._publish_timeout_seconds = publish_timeout_seconds

        self._client: mqtt.Client | None = None
        self._task: asyncio.Task[None] | None = None
        self._stop_event: asyncio.Event | None = None
        self._published_count = 0

    @property
    def published_count(self) -> int:
        """Total Bundles successfully published (broker-acknowledged) since start()."""
        return self._published_count

    def topic_for(self, bundle: dict[str, Any]) -> str:
        patient_id = _extract_patient_id(bundle)
        return f"{self._topic_prefix}/{patient_id}"

    async def start(self) -> None:
        client = mqtt.Client(
            callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
            client_id=self._client_id,
        )
        client.on_connect = self._on_connect
        client.on_disconnect = self._on_disconnect

        if self._username is not None:
            client.username_pw_set(self._username, self._password)

        if self._use_tls:
            client.tls_set()  # system CA trust store; broker cert must chain to it
        else:
            # HAZARD-STREAM-004: explicit, loud audit-trail entry for an
            # unencrypted broker connection.
            _log.warning(
                "mqtt_publisher.tls_disabled",
                broker_host=self._broker_host,
                risk="Clinical telemetry will be published in PLAINTEXT over the network.",
            )

        client.reconnect_delay_set(
            min_delay=_DEFAULT_MIN_RECONNECT_DELAY_SECONDS,
            max_delay=_DEFAULT_MAX_RECONNECT_DELAY_SECONDS,
        )
        # connect_async() + loop_start(): connection and all reconnection
        # attempts happen on paho's own network thread, never blocking the
        # asyncio event loop and never raising into this coroutine on a
        # transient outage (HAZARD-STREAM-003).
        client.connect_async(self._broker_host, self._broker_port, keepalive=60)
        client.loop_start()

        self._client = client
        self._stop_event = asyncio.Event()
        self._task = asyncio.create_task(self._run_loop())
        _log.info(
            "mqtt_publisher.start",
            broker_host=self._broker_host,
            broker_port=self._broker_port,
            topic_prefix=self._topic_prefix,
            use_tls=self._use_tls,
        )

    async def stop(self) -> None:
        if self._stop_event is not None:
            self._stop_event.set()
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
            self._task = None
        if self._client is not None:
            self._client.loop_stop()
            self._client.disconnect()
            self._client = None
        _log.info("mqtt_publisher.stop", published_count=self._published_count)

    async def __aenter__(self) -> MQTTPublisher:
        await self.start()
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        await self.stop()

    # ── Background Loop ───────────────────────────────────────────────────────

    async def _run_loop(self) -> None:
        if self._stop_event is None:
            raise RuntimeError("MQTTPublisher._run_loop() called before start().")
        loop = asyncio.get_event_loop()
        while not self._stop_event.is_set():
            batch = self._buffer.drain(self._drain_batch_size)
            if not batch:
                await asyncio.sleep(self._publish_interval_seconds)
                continue

            unpublished = await loop.run_in_executor(
                None, functools.partial(self._publish_batch_sync, batch)
            )
            self._published_count += len(batch) - len(unpublished)

            if unpublished:
                dropped = self._buffer.requeue_front(unpublished)
                if dropped:
                    _log.warning(
                        "mqtt_publisher.requeue_overflow",
                        requeued=len(unpublished),
                        dropped=dropped,
                    )
                await asyncio.sleep(self._retry_backoff_seconds)
            else:
                await asyncio.sleep(self._publish_interval_seconds)

    def _publish_batch_sync(self, batch: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """
        Publish a drained batch in order; runs on the executor thread pool.

        Stops attempting further items in this batch after the first
        failure (a down/unreachable broker won't recover mid-batch) and
        returns every item from that point onward — including the failed
        one — for the caller to requeue, preserving chronological order.
        """
        if self._client is None:
            raise RuntimeError(
                "MQTTPublisher._publish_batch_sync() called before start()."
            )
        unpublished: list[dict[str, Any]] = []
        failing = False

        for bundle in batch:
            if failing:
                unpublished.append(bundle)
                continue

            topic = self.topic_for(bundle)
            payload = json.dumps(bundle)
            try:
                info = self._client.publish(topic, payload, qos=self._qos)
                if info.rc != mqtt.MQTT_ERR_SUCCESS:
                    raise RuntimeError(
                        f"paho-mqtt publish() returned rc={info.rc} "
                        f"({mqtt.error_string(info.rc)})"
                    )
                if self._qos > 0:
                    info.wait_for_publish(timeout=self._publish_timeout_seconds)
            except Exception as exc:  # noqa: BLE001 - any publish failure requeues, never drops
                _log.warning(
                    "mqtt_publisher.publish_failed", topic=topic, error=str(exc)
                )
                unpublished.append(bundle)
                failing = True

        return unpublished

    # ── Connection Callbacks (VERSION2 API) ─────────────────────────────────────

    @staticmethod
    def _on_connect(
        client: mqtt.Client,
        userdata: Any,
        connect_flags: Any,
        reason_code: Any,
        properties: Any,
    ) -> None:
        _log.info("mqtt_publisher.broker_connected", reason_code=str(reason_code))

    @staticmethod
    def _on_disconnect(
        client: mqtt.Client,
        userdata: Any,
        disconnect_flags: Any,
        reason_code: Any,
        properties: Any,
    ) -> None:
        _log.warning("mqtt_publisher.broker_disconnected", reason_code=str(reason_code))
