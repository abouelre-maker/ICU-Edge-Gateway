"""
Unit Tests — StoreAndForwardRingBuffer.

IEC 62304 §5.7: Verifies bounded-capacity, drop-oldest-on-overflow, and
FIFO drain semantics used by the Phase 5 streaming layer for edge/WAN
resilience (ISO 14971 HAZARD-STREAM-002).
"""

from __future__ import annotations

import pytest
from infrastructure.streaming.ring_buffer import StoreAndForwardRingBuffer


class TestConstruction:
    def test_rejects_zero_capacity(self) -> None:
        with pytest.raises(ValueError, match="positive integer"):
            StoreAndForwardRingBuffer(capacity=0)

    def test_rejects_negative_capacity(self) -> None:
        with pytest.raises(ValueError, match="positive integer"):
            StoreAndForwardRingBuffer(capacity=-1)

    def test_empty_buffer_state(self) -> None:
        buf: StoreAndForwardRingBuffer[int] = StoreAndForwardRingBuffer(capacity=5)
        assert buf.size() == 0
        assert buf.capacity == 5
        assert buf.dropped_count == 0
        assert buf.peek_all() == []


class TestPushWithinCapacity:
    def test_push_below_capacity_never_drops(self) -> None:
        buf: StoreAndForwardRingBuffer[int] = StoreAndForwardRingBuffer(capacity=3)
        assert buf.push(1) is False
        assert buf.push(2) is False
        assert buf.size() == 2
        assert buf.dropped_count == 0

    def test_push_at_exact_capacity_does_not_drop(self) -> None:
        buf: StoreAndForwardRingBuffer[int] = StoreAndForwardRingBuffer(capacity=2)
        assert buf.push(1) is False
        assert buf.push(2) is False
        assert buf.size() == 2
        assert buf.dropped_count == 0


class TestOverflowDropOldest:
    def test_overflow_drops_oldest_and_reports_true(self) -> None:
        buf: StoreAndForwardRingBuffer[int] = StoreAndForwardRingBuffer(capacity=2)
        buf.push(1)
        buf.push(2)
        dropped = buf.push(3)  # should evict 1
        assert dropped is True
        assert buf.size() == 2
        assert buf.peek_all() == [2, 3]

    def test_dropped_count_accumulates(self) -> None:
        buf: StoreAndForwardRingBuffer[int] = StoreAndForwardRingBuffer(capacity=1)
        buf.push(1)
        buf.push(2)
        buf.push(3)
        assert buf.dropped_count == 2
        assert buf.peek_all() == [3]


class TestDrain:
    def test_drain_all_returns_fifo_order_and_empties_buffer(self) -> None:
        buf: StoreAndForwardRingBuffer[int] = StoreAndForwardRingBuffer(capacity=5)
        for i in range(4):
            buf.push(i)
        drained = buf.drain()
        assert drained == [0, 1, 2, 3]
        assert buf.size() == 0

    def test_drain_partial_leaves_remainder_in_fifo_order(self) -> None:
        buf: StoreAndForwardRingBuffer[int] = StoreAndForwardRingBuffer(capacity=5)
        for i in range(4):
            buf.push(i)
        drained = buf.drain(max_items=2)
        assert drained == [0, 1]
        assert buf.peek_all() == [2, 3]

    def test_drain_more_than_available_returns_all(self) -> None:
        buf: StoreAndForwardRingBuffer[int] = StoreAndForwardRingBuffer(capacity=5)
        buf.push(1)
        drained = buf.drain(max_items=100)
        assert drained == [1]

    def test_drain_empty_buffer_returns_empty_list(self) -> None:
        buf: StoreAndForwardRingBuffer[int] = StoreAndForwardRingBuffer(capacity=5)
        assert buf.drain() == []


class TestPeekDoesNotMutate:
    def test_peek_all_does_not_remove_items(self) -> None:
        buf: StoreAndForwardRingBuffer[int] = StoreAndForwardRingBuffer(capacity=5)
        buf.push(1)
        buf.push(2)
        assert buf.peek_all() == [1, 2]
        assert buf.size() == 2  # unchanged after peek


class TestRequeueFront:
    """
    Used by a forwarder (e.g. MQTTPublisher) that drained a batch but failed
    to deliver some or all of it — undelivered items go back to the front
    of the buffer, ahead of anything pushed since, so retries happen in
    original chronological order.
    """

    def test_requeue_restores_items_ahead_of_newer_pushes(self) -> None:
        buf: StoreAndForwardRingBuffer[int] = StoreAndForwardRingBuffer(capacity=10)
        buf.push(1)
        buf.push(2)
        drained = buf.drain()  # [1, 2]
        buf.push(3)  # pushed while [1, 2] were "in flight" to a forwarder

        dropped = buf.requeue_front(drained)

        assert dropped == 0
        assert buf.peek_all() == [1, 2, 3]

    def test_requeue_preserves_relative_order_of_requeued_items(self) -> None:
        buf: StoreAndForwardRingBuffer[int] = StoreAndForwardRingBuffer(capacity=10)
        buf.requeue_front([1, 2, 3])
        assert buf.peek_all() == [1, 2, 3]

    def test_requeue_into_empty_buffer(self) -> None:
        buf: StoreAndForwardRingBuffer[int] = StoreAndForwardRingBuffer(capacity=10)
        dropped = buf.requeue_front([1, 2])
        assert dropped == 0
        assert buf.peek_all() == [1, 2]

    def test_requeue_overflow_drops_newest_not_the_requeued_items(self) -> None:
        buf: StoreAndForwardRingBuffer[int] = StoreAndForwardRingBuffer(capacity=3)
        buf.push(10)
        buf.push(11)
        buf.push(12)  # buffer now full: [10, 11, 12]

        dropped = buf.requeue_front([1, 2])  # would exceed capacity by 2

        assert dropped == 2
        # The two oldest (requeued, retried) items survive; the newest
        # regular pushes are evicted to make room for them.
        assert buf.peek_all() == [1, 2, 10]
        assert buf.dropped_count == 2

    def test_requeue_empty_list_is_a_no_op(self) -> None:
        buf: StoreAndForwardRingBuffer[int] = StoreAndForwardRingBuffer(capacity=5)
        buf.push(1)
        dropped = buf.requeue_front([])
        assert dropped == 0
        assert buf.peek_all() == [1]
