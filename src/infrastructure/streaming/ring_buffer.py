"""
StoreAndForwardRingBuffer — Bounded FIFO Buffer for Edge/WAN Resilience.

Phase 5 Section A: used by the MLLP listener (and, in a later Phase 5 step,
the MQTT edge->cloud publisher) to hold FHIR Bundles / telemetry payloads
produced on the edge appliance while the cloud connection is unavailable,
so a WAN interruption does not block message ingestion.

IEC 62304 §5.3: Generic, dependency-free utility — no clinical logic. Reused
by any transport that needs store-and-forward semantics.

ISO 14971 HAZARD-STREAM-002 (PROPOSED — pending human risk-management
sign-off; this is a new hazard for new code, not a resolution of an existing
one):
  During a prolonged WAN/cloud outage, telemetry can accumulate faster than
  it can be forwarded once connectivity resumes. An unbounded buffer risks
  unbounded memory growth on the edge appliance; a bounded buffer that
  silently discards data on overflow risks losing clinical telemetry with no
  audit trail.
  Mitigation implemented here: the buffer has a fixed capacity, uses an
  explicit drop-oldest-on-overflow policy, and every drop is counted AND
  logged at WARNING level so the loss is visible in the edge appliance's
  audit trail even though the dropped payload itself is gone. This does NOT
  eliminate the residual risk of telemetry loss during extended outages —
  it only makes the loss observable and countable. Buffer capacity (i.e. how
  many hours/messages of outage a given clinical deployment must tolerate
  before data loss begins) is a clinical risk-acceptance decision and
  requires human sign-off before production sizing.
"""

from __future__ import annotations

import threading
from collections import deque
from typing import Generic, TypeVar

import structlog

_log: structlog.BoundLogger = structlog.get_logger(__name__)

T = TypeVar("T")


class StoreAndForwardRingBuffer(Generic[T]):
    """
    Thread-safe bounded FIFO buffer with drop-oldest-on-overflow semantics.

    Safe to share between the asyncio event loop thread (e.g. MLLPListener,
    which calls push()) and a separate forwarding worker/thread (e.g. a
    future MQTT publisher, which calls drain()) — all mutating operations
    are guarded by a single lock.
    """

    def __init__(self, capacity: int) -> None:
        if capacity <= 0:
            raise ValueError(
                "StoreAndForwardRingBuffer capacity must be a positive integer. "
                f"Got {capacity!r}."
            )
        self._capacity = capacity
        self._items: deque[T] = deque()
        self._dropped_count = 0
        self._lock = threading.Lock()

    @property
    def capacity(self) -> int:
        return self._capacity

    @property
    def dropped_count(self) -> int:
        """Total items ever dropped due to overflow (monotonically increasing)."""
        with self._lock:
            return self._dropped_count

    def size(self) -> int:
        with self._lock:
            return len(self._items)

    def push(self, item: T) -> bool:
        """
        Append an item to the buffer.

        If the buffer is at capacity, the oldest item is dropped to make
        room (FIFO overflow policy) and the drop is logged and counted.

        Returns:
            True if an existing item was dropped to make room, else False.
        """
        dropped = False
        with self._lock:
            if len(self._items) >= self._capacity:
                self._items.popleft()
                self._dropped_count += 1
                dropped = True
            self._items.append(item)
        if dropped:
            # HAZARD-STREAM-002 mitigation: overflow is always observable.
            _log.warning(
                "store_and_forward_ring_buffer.overflow_drop",
                capacity=self._capacity,
                total_dropped=self.dropped_count,
            )
        return dropped

    def drain(self, max_items: int | None = None) -> list[T]:
        """
        Remove and return up to `max_items` oldest items (FIFO order).

        Args:
            max_items: Maximum number of items to remove. None drains
                       everything currently buffered.
        """
        with self._lock:
            n = (
                len(self._items)
                if max_items is None
                else min(max_items, len(self._items))
            )
            return [self._items.popleft() for _ in range(n)]

    def peek_all(self) -> list[T]:
        """Return a snapshot of all currently buffered items without removing them."""
        with self._lock:
            return list(self._items)
