"""
F-03 — MLLP stream limits: the 1 MiB frame cap must actually work (asyncio's
64 KiB default limit used to raise an unhandled LimitOverrunError and reset
the connection), plus read timeouts and a concurrent-connection cap.
"""

from __future__ import annotations

import asyncio
from typing import Any

from infrastructure.streaming.mllp_listener import (
    _CARRIAGE_RETURN,
    _END_BLOCK,
    _START_BLOCK,
    MLLPListener,
)
from infrastructure.streaming.ring_buffer import StoreAndForwardRingBuffer

_OK = (
    "MSH|^~\\&|MON|ICU|EHR|HOSP|20260929110000||ORU^R01|F03|P|2.5.1\r"
    "PID|1||PT-F03^^^H^MR\r"
    "OBX|1|NM|8867-4^HR^LN||72|/min|||||F|||20260929110000\r"
)


def _frame(payload: bytes) -> bytes:
    return _START_BLOCK + payload + _END_BLOCK + _CARRIAGE_RETURN


async def _ack_or_eof(listener: MLLPListener, data: bytes) -> bytes:
    reader, writer = await asyncio.open_connection("127.0.0.1", listener.port)
    writer.write(data)
    await writer.drain()
    try:
        return await asyncio.wait_for(reader.read(65536), timeout=5)
    finally:
        writer.close()
        await writer.wait_closed()


def _listener(**kw: Any) -> MLLPListener:
    return MLLPListener(
        host="127.0.0.1", port=0, forward_buffer=StoreAndForwardRingBuffer(capacity=10), **kw
    )


async def test_200_kb_frame_gets_a_nak_not_a_reset_and_listener_survives() -> None:
    errors: list[Any] = []
    loop = asyncio.get_running_loop()
    loop.set_exception_handler(lambda _l, ctx: errors.append(ctx))
    lst = _listener()
    await lst.start()
    try:
        resp = await _ack_or_eof(lst, _frame(b"A" * 200_000))
        assert b"MSA|AE|" in resp  # explicit negative ACK, not a reset
        ok = await _ack_or_eof(lst, _frame(_OK.encode()))
        assert b"MSA|AA|" in ok  # listener still accepting
    finally:
        await lst.stop()
        loop.set_exception_handler(None)
    assert errors == []  # no unhandled LimitOverrunError


async def test_frame_above_cap_is_refused_cleanly_and_listener_survives() -> None:
    errors: list[Any] = []
    loop = asyncio.get_running_loop()
    loop.set_exception_handler(lambda _l, ctx: errors.append(ctx))
    lst = _listener(max_frame_bytes=100_000)
    await lst.start()
    try:
        await _ack_or_eof(lst, _frame(b"A" * 300_000))
        ok = await _ack_or_eof(lst, _frame(_OK.encode()))
        assert b"MSA|AA|" in ok
    finally:
        await lst.stop()
        loop.set_exception_handler(None)
    assert errors == []


async def test_stalled_frame_times_out_and_closes() -> None:
    lst = _listener(frame_timeout_seconds=0.2)
    await lst.start()
    try:
        reader, writer = await asyncio.open_connection("127.0.0.1", lst.port)
        writer.write(_START_BLOCK + b"MSH|^~\\&|SLOW")  # never terminated
        await writer.drain()
        data = await asyncio.wait_for(reader.read(), timeout=3)
        assert data == b""  # server closed the stalled connection
        writer.close()
        ok = await _ack_or_eof(lst, _frame(_OK.encode()))
        assert b"MSA|AA|" in ok
    finally:
        await lst.stop()


async def test_connections_above_the_cap_are_refused() -> None:
    lst = _listener(max_connections=1)
    await lst.start()
    try:
        r1, w1 = await asyncio.open_connection("127.0.0.1", lst.port)
        await asyncio.sleep(0.1)
        r2, w2 = await asyncio.open_connection("127.0.0.1", lst.port)
        data = await asyncio.wait_for(r2.read(), timeout=3)
        assert data == b""  # second connection closed immediately
        w1.write(_frame(_OK.encode()))
        await w1.drain()
        assert b"MSA|AA|" in await asyncio.wait_for(r1.read(65536), timeout=5)
        w1.close()
        w2.close()
    finally:
        await lst.stop()
