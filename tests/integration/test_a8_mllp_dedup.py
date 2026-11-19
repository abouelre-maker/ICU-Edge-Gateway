"""
A8-1 / F03-1: MLLP retransmissions and oversized frames.

- A retransmitted message (same MSH-3, MSH-4, MSH-10) is acknowledged AA again
  but is not processed or forwarded a second time.
- A message that was refused is not remembered, so a corrected resend works.
- An oversized frame is answered with AR before the connection closes.
"""

from __future__ import annotations

import asyncio

from infrastructure.streaming.mllp_listener import MLLPListener, _dedup_key
from infrastructure.streaming.ring_buffer import StoreAndForwardRingBuffer

from tests.integration.test_mllp_listener import FULL_ORU

_SB, _EB, _CR = b"\x0b", b"\x1c", b"\x0d"


def _frame(msg: str) -> bytes:
    return _SB + msg.encode("utf-8") + _EB + _CR


async def _exchange(listener: MLLPListener, *messages: str) -> list[bytes]:
    reader, writer = await asyncio.open_connection("127.0.0.1", listener.port)
    acks = []
    for m in messages:
        writer.write(_frame(m))
        await writer.drain()
        acks.append(await asyncio.wait_for(reader.readuntil(_EB + _CR), timeout=5))
    writer.close()
    await writer.wait_closed()
    return acks


async def _listener(**kw: object) -> MLLPListener:
    lst = MLLPListener(port=0, forward_buffer=StoreAndForwardRingBuffer(capacity=50), **kw)  # type: ignore[arg-type]
    await lst.start()
    return lst


async def test_retransmission_is_acked_but_not_reprocessed() -> None:
    lst = await _listener()
    try:
        acks = await _exchange(lst, FULL_ORU, FULL_ORU, FULL_ORU)
        assert all(b"MSA|AA|MSG001|" in a for a in acks)
        assert lst.forward_buffer.size() == 1
    finally:
        await lst.stop()


async def test_retransmission_on_a_new_connection_is_not_reprocessed() -> None:
    lst = await _listener()
    try:
        await _exchange(lst, FULL_ORU)
        (ack,) = await _exchange(lst, FULL_ORU)
        assert b"MSA|AA|MSG001|" in ack
        assert lst.forward_buffer.size() == 1
    finally:
        await lst.stop()


async def test_same_control_id_from_another_sender_is_processed() -> None:
    lst = await _listener()
    try:
        other = FULL_ORU.replace("GENERIC_MONITOR|ICU_UNIT", "GENERIC_MONITOR|ICU_WEST")
        await _exchange(lst, FULL_ORU, other)
        assert lst.forward_buffer.size() == 2
    finally:
        await lst.stop()


async def test_refused_message_is_not_remembered() -> None:
    lst = await _listener()
    try:
        bad = FULL_ORU.replace("ORU^R01", "ADT^A01")  # AR: unsupported type
        acks = await _exchange(lst, bad, FULL_ORU)
        assert b"MSA|AR|" in acks[0]
        assert b"MSA|AA|" in acks[1]
        assert lst.forward_buffer.size() == 1
    finally:
        await lst.stop()


async def test_dedup_memory_is_bounded() -> None:
    lst = await _listener(dedup_capacity=2)
    try:
        msgs = [FULL_ORU.replace("|MSG001|", f"|M{i}|") for i in range(3)]
        await _exchange(lst, *msgs)
        await _exchange(lst, msgs[0])  # evicted -> processed again
        assert lst.forward_buffer.size() == 4
    finally:
        await lst.stop()


def test_dedup_key_reads_sender_facility_and_control_id() -> None:
    assert _dedup_key(FULL_ORU.encode()) == ("GENERIC_MONITOR", "ICU_UNIT", "MSG001")


def test_message_without_control_id_has_no_key() -> None:
    assert _dedup_key(FULL_ORU.replace("|MSG001|", "||").encode()) is None


async def test_oversized_frame_over_stream_limit_gets_ar() -> None:
    lst = await _listener(max_frame_bytes=1024)
    try:
        reader, writer = await asyncio.open_connection("127.0.0.1", lst.port)
        writer.write(_SB + b"MSH|" + b"X" * 200_000 + _EB + _CR)
        await writer.drain()
        data = await asyncio.wait_for(reader.read(), timeout=5)
        assert b"MSA|AR|" in data
        assert lst.forward_buffer.size() == 0
        writer.close()
    finally:
        await lst.stop()
