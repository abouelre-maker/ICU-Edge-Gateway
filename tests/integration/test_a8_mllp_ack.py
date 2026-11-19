"""
A8 — MLLP acknowledgement correctness.
See regulatory/findings/A8.md (unsigned PROPOSAL).
"""

from __future__ import annotations

import asyncio

import pytest
from domain.entities.patient_context import SpO2Scale
from infrastructure.streaming.mllp_listener import (
    _CARRIAGE_RETURN,
    _END_BLOCK,
    _START_BLOCK,
    MLLPListener,
)
from infrastructure.streaming.ring_buffer import StoreAndForwardRingBuffer

_OBX = (
    "OBX|1|NM|8867-4^Heart rate^LN||72|/min|||||F|||20260929110000\r"
    "OBX|2|NM|59408-5^SpO2^LN||95|%|||||F|||20260929110000\r"
)


def _msg(control_id: str, msh9: str = "ORU^R01", obx: str = _OBX) -> str:
    return (
        f"MSH|^~\\&|MON|ICU|EHR|HOSP|20260929110000||{msh9}|{control_id}|P|2.5.1\r"
        f"PID|1||PT-A8^^^HOSP^MR\r{obx}"
    )


def _frame(payload: str) -> bytes:
    return _START_BLOCK + payload.encode("utf-8") + _END_BLOCK + _CARRIAGE_RETURN


async def _roundtrip(listener: MLLPListener, payload: str) -> str:
    reader, writer = await asyncio.open_connection("127.0.0.1", listener.port)
    writer.write(_frame(payload))
    await writer.drain()
    resp = await asyncio.wait_for(reader.readuntil(_END_BLOCK + _CARRIAGE_RETURN), timeout=5)
    writer.close()
    await writer.wait_closed()
    return resp[1:-2].decode("utf-8")


def _segment(ack: str, name: str) -> list[str]:
    return next(s for s in ack.split("\r") if s.startswith(name + "|")).split("|")


@pytest.fixture
async def listener():  # noqa: ANN201
    lst = MLLPListener(
        host="127.0.0.1", port=0, forward_buffer=StoreAndForwardRingBuffer(capacity=10)
    )
    await lst.start()
    yield lst
    await lst.stop()


async def test_msa2_echoes_incoming_msh10(listener: MLLPListener) -> None:
    ack = await _roundtrip(listener, _msg("CTRL-A8-1"))
    msa = _segment(ack, "MSA")
    assert msa[1] == "AA"
    assert msa[2] == "CTRL-A8-1"


async def test_ack_control_ids_are_unique(listener: MLLPListener) -> None:
    a1 = await _roundtrip(listener, _msg("C-1"))
    a2 = await _roundtrip(listener, _msg("C-2"))
    assert _segment(a1, "MSH")[9] != _segment(a2, "MSH")[9]


async def test_unsupported_message_type_is_rejected_with_ar(listener: MLLPListener) -> None:
    ack = await _roundtrip(listener, _msg("CTRL-ADT", msh9="ADT^A01"))
    msa = _segment(ack, "MSA")
    assert msa[1] == "AR"
    assert msa[2] == "CTRL-ADT"
    assert listener.forward_buffer.size() == 0


async def test_batch_envelope_is_rejected_with_ar(listener: MLLPListener) -> None:
    ack = await _roundtrip(listener, "FHS|^~\\&|MON|ICU\rBHS|^~\\&|MON|ICU\r" + _msg("B-1"))
    assert _segment(ack, "MSA")[1] == "AR"
    assert listener.forward_buffer.size() == 0


async def test_message_with_no_usable_observation_is_not_aa(listener: MLLPListener) -> None:
    ack = await _roundtrip(
        listener, _msg("CTRL-EMPTY", obx="OBX|1|NM|ZZZ^Unknown^99L||1|x|||||F\r")
    )
    msa = _segment(ack, "MSA")
    assert msa[1] == "AE"
    assert msa[2] == "CTRL-EMPTY"
    assert listener.forward_buffer.size() == 0


async def test_spo2_scale_is_resolved_per_patient() -> None:
    seen: list[str] = []

    def resolver(patient_id: str) -> SpO2Scale | None:
        seen.append(patient_id)
        return SpO2Scale.SCALE_2

    lst = MLLPListener(
        host="127.0.0.1",
        port=0,
        forward_buffer=StoreAndForwardRingBuffer(capacity=10),
        spo2_scale_resolver=resolver,
    )
    await lst.start()
    try:
        ack = await _roundtrip(lst, _msg("CTRL-SCALE"))
    finally:
        await lst.stop()
    assert _segment(ack, "MSA")[1] == "AA"
    assert seen == ["PT-A8"]
