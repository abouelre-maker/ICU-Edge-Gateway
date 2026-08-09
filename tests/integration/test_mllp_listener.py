"""
Integration Tests — MLLPListener (Phase 5 Section A streaming layer).

IEC 62304 §5.7: Verifies the MLLP transport end-to-end against a real
asyncio TCP socket — framing, ACK/NAK generation, store-and-forward buffer
population, and malformed-frame rejection (ISO 14971 HAZARD-STREAM-001).

Does not re-verify DSP/NEWS2/FHIR numeric correctness — that is owned by
existing tests/integration/test_api_ingest.py and the unit suites. This
file verifies the new transport wiring only.
"""

from __future__ import annotations

import asyncio

import pytest
from infrastructure.streaming.mllp_listener import (
    _CARRIAGE_RETURN,
    _END_BLOCK,
    _START_BLOCK,
    MLLPListener,
)
from infrastructure.streaming.ring_buffer import StoreAndForwardRingBuffer

# Same fixture message used by tests/integration/test_api_ingest.py::FULL_ORU
FULL_ORU = (
    "MSH|^~\\&|GENERIC_MONITOR|ICU_UNIT|EHR|HOSPITAL|20240115100000"
    "||ORU^R01|MSG001|P|2.5.1\r"
    "PID|1||PT-MLLP-001^^^HOSP^MR||DOE^JOHN||19800101|M\r"
    "OBR|1||ORDER-001|||||20240115100000\r"
    "OBX|1|NM|8867-4^Heart rate^LN||72|/min|60-100||||F|||20240115100000\r"
    "OBX|2|NM|59408-5^SpO2^LN||98|%|95-100||||F|||20240115100000\r"
    "OBX|3|NM|9279-1^Respiratory rate^LN||16|/min|12-20||||F|||20240115100000\r"
    "OBX|4|NM|8480-6^Systolic BP^LN||120|mmHg|90-140||||F|||20240115100000\r"
    "OBX|5|NM|8310-5^Temperature^LN||37.0|Cel|36.1-38.0||||F|||20240115100000\r"
    "OBX|6|NM|57834-7^Supplemental O2^LN||0||||||F|||20240115100000\r"
)

_INVALID_HL7 = "THIS IS NOT HL7\rNOT AT ALL\r"


def _mllp_frame(payload: str) -> bytes:
    return _START_BLOCK + payload.encode("utf-8") + _END_BLOCK + _CARRIAGE_RETURN


async def _connect(
    listener: MLLPListener,
) -> tuple[asyncio.StreamReader, asyncio.StreamWriter]:
    return await asyncio.open_connection(host="127.0.0.1", port=listener.port)


@pytest.fixture
async def listener():
    buf: StoreAndForwardRingBuffer = StoreAndForwardRingBuffer(capacity=10)
    lst = MLLPListener(host="127.0.0.1", port=0, forward_buffer=buf)
    await lst.start()
    yield lst
    await lst.stop()


class TestValidFrameAccepted:
    async def test_valid_frame_returns_aa_ack(self, listener: MLLPListener) -> None:
        reader, writer = await _connect(listener)
        writer.write(_mllp_frame(FULL_ORU))
        await writer.drain()

        response = await asyncio.wait_for(
            reader.readuntil(_END_BLOCK + _CARRIAGE_RETURN), timeout=5
        )
        ack_text = response[1:-2].decode("utf-8")  # strip VT ... FS CR

        assert "MSA|AA|" in ack_text
        writer.close()
        await writer.wait_closed()

    async def test_valid_frame_populates_forward_buffer_with_fhir_bundle(
        self, listener: MLLPListener
    ) -> None:
        reader, writer = await _connect(listener)
        writer.write(_mllp_frame(FULL_ORU))
        await writer.drain()
        await asyncio.wait_for(
            reader.readuntil(_END_BLOCK + _CARRIAGE_RETURN), timeout=5
        )

        assert listener.forward_buffer.size() == 1
        bundle = listener.forward_buffer.peek_all()[0]
        assert bundle["resourceType"] == "Bundle"
        writer.close()
        await writer.wait_closed()

    async def test_multiple_frames_on_one_persistent_connection(
        self, listener: MLLPListener
    ) -> None:
        reader, writer = await _connect(listener)
        for _ in range(3):
            writer.write(_mllp_frame(FULL_ORU))
            await writer.drain()
            resp = await asyncio.wait_for(
                reader.readuntil(_END_BLOCK + _CARRIAGE_RETURN), timeout=5
            )
            assert b"MSA|AA|" in resp

        assert listener.forward_buffer.size() == 3
        writer.close()
        await writer.wait_closed()


class TestMalformedFrameRejected:
    async def test_syntactically_invalid_hl7_returns_ae_nak(
        self, listener: MLLPListener
    ) -> None:
        reader, writer = await _connect(listener)
        writer.write(_mllp_frame(_INVALID_HL7))
        await writer.drain()

        response = await asyncio.wait_for(
            reader.readuntil(_END_BLOCK + _CARRIAGE_RETURN), timeout=5
        )
        ack_text = response[1:-2].decode("utf-8")

        assert "MSA|AE|" in ack_text
        assert listener.forward_buffer.size() == 0
        writer.close()
        await writer.wait_closed()

    async def test_connection_closed_mid_frame_does_not_crash_listener(
        self, listener: MLLPListener
    ) -> None:
        reader, writer = await _connect(listener)
        # Start block + partial body, then abrupt disconnect — no terminator ever sent.
        writer.write(_START_BLOCK + b"MSH|^~\\&|PARTIAL")
        await writer.drain()
        writer.close()
        await writer.wait_closed()

        # Listener must still be able to accept a fresh, valid connection afterward.
        reader2, writer2 = await _connect(listener)
        writer2.write(_mllp_frame(FULL_ORU))
        await writer2.drain()
        response = await asyncio.wait_for(
            reader2.readuntil(_END_BLOCK + _CARRIAGE_RETURN), timeout=5
        )
        assert b"MSA|AA|" in response
        writer2.close()
        await writer2.wait_closed()


class TestOversizedFrameRejected:
    async def test_frame_exceeding_max_bytes_is_rejected(self) -> None:
        buf: StoreAndForwardRingBuffer = StoreAndForwardRingBuffer(capacity=10)
        listener = MLLPListener(
            host="127.0.0.1", port=0, forward_buffer=buf, max_frame_bytes=64
        )
        await listener.start()
        try:
            reader, writer = await _connect(listener)
            writer.write(_mllp_frame(FULL_ORU))  # well over 64 bytes
            await writer.drain()
            # Listener closes the connection rather than ACKing an oversized frame.
            data = await asyncio.wait_for(reader.read(), timeout=5)
            assert data == b""  # connection closed with no ACK sent
            assert buf.size() == 0
        finally:
            await listener.stop()
