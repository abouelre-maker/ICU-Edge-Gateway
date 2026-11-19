"""
F-02 — unauthenticated CPU DoS: payload caps and off-loop processing.

Caps are engineering limits (not clinical): request body 256 KiB, 200 OBX per
HL7 message, 20 000 samples per waveform — all configurable.
"""

from __future__ import annotations

import asyncio
import json
import time
from datetime import datetime, timezone

import pytest
from httpx import AsyncClient
from infrastructure.adapters.hl7v2_adapter import HL7v2Adapter

_NOW = datetime.now(tz=timezone.utc)


def _hl7(n_obx: int) -> str:
    ts = _NOW.strftime("%Y%m%d%H%M%S")
    lines = [f"MSH|^~\\&|MON|ICU|EHR|HOSP|{ts}||ORU^R01|F02|P|2.5.1", "PID|1||PT-F02^^^H^MR"]
    lines += [f"OBX|{i}|NM|8867-4^HR^LN||72|/min|||||F" for i in range(1, n_obx + 1)]
    return "\r".join(lines)


def _waveform_payload(n: int) -> dict[str, object]:
    return {
        "patient_id": "PT-F02",
        "samples": [
            {
                "vital_sign_type": "HEART_RATE",
                "value": 72,
                "unit": "bpm",
                "timestamp": _NOW.isoformat(),
                "waveform": [round(0.5 * ((i * 7) % 13), 3) for i in range(n)],
                "sampling_rate_hz": 250.0,
            }
        ],
    }


async def test_oversized_http_body_is_413(client: AsyncClient) -> None:
    body = json.dumps({"patient_id": "PT-F02", "samples": [], "pad": "x" * 300_000})
    resp = await client.post(
        "/api/v1/vitals", content=body, headers={"Content-Type": "application/json"}
    )
    assert resp.status_code == 413


async def test_oversized_hl7_body_is_413(client: AsyncClient) -> None:
    resp = await client.post(
        "/api/v1/ingest",
        content="MSH|" + "x" * 300_000,
        headers={"Content-Type": "text/plain"},
    )
    assert resp.status_code == 413


def test_too_many_obx_segments_is_rejected_explicitly() -> None:
    with pytest.raises(ValueError, match="OBX"):
        HL7v2Adapter().parse(_hl7(201))


def test_obx_cap_boundary_is_accepted() -> None:
    assert len(HL7v2Adapter().parse(_hl7(200)).samples) == 200


async def test_oversized_waveform_is_rejected(client: AsyncClient) -> None:
    resp = await client.post("/api/v1/vitals", json=_waveform_payload(20_001))
    assert resp.status_code in (413, 422)


async def test_processing_does_not_block_the_event_loop(client: AsyncClient) -> None:
    """
    A large-but-allowed waveform (15 000 samples, within every cap) must not
    stall other coroutines by more than 150 ms. Before the F-02 fix, a
    10 000-sample waveform stalled the loop ~610 ms (measured 2026-09-30).
    """
    worst = 0.0
    stop = False

    async def ticker() -> None:
        nonlocal worst
        while not stop:
            t0 = time.perf_counter()
            await asyncio.sleep(0.01)
            worst = max(worst, time.perf_counter() - t0 - 0.01)

    task = asyncio.create_task(ticker())
    await asyncio.sleep(0.03)  # let the ticker start before the request
    resp = await client.post("/api/v1/vitals", json=_waveform_payload(15_000))
    await asyncio.sleep(0.03)  # let the ticker observe any lateness
    stop = True
    await task
    assert resp.status_code == 200
    assert worst < 0.15, f"event loop stalled {worst * 1000:.0f} ms"
