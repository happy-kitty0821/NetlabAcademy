"""
simulator_core.scheduler
~~~~~~~~~~~~~~~~~~~~~~~~
Priority-queue event scheduler for the discrete-event simulation.

The heap is ordered by ``(event.time, event.seq)``.  Because ``seq`` is a
monotonically increasing integer assigned at schedule time, no two entries in
the heap have the same key — the ordering is total and deterministic.

No host I/O, no socket imports.
"""

from __future__ import annotations

import heapq
from typing import Optional

from simulator_core.events import SimulationEvent
from simulator_core.exceptions import SimulationLimitError


class EventScheduler:
    """
    Min-heap priority queue for simulation events.

    Ordering
    --------
    Events are popped in ascending ``(time, seq)`` order.  ``seq`` is assigned
    by :meth:`next_seq` at the moment an event is scheduled, ensuring that
    events with the same logical timestamp are processed in insertion order.

    Limits
    ------
    If :meth:`schedule` is called when the queue already contains
    ``max_depth`` events, :class:`~simulator_core.exceptions.SimulationLimitError`
    is raised.  Existing state is not mutated on a limit violation.
    """

    DEFAULT_MAX_DEPTH: int = 10_000

    def __init__(self, max_depth: int = DEFAULT_MAX_DEPTH) -> None:
        self._heap: list[tuple[int, int, SimulationEvent]] = []
        self._seq: int = 0
        self._max_depth: int = max_depth

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def schedule(self, event: SimulationEvent) -> None:
        """
        Add *event* to the queue.

        Raises
        ------
        SimulationLimitError
            If the queue already contains ``max_depth`` events.
        """
        if len(self._heap) >= self._max_depth:
            raise SimulationLimitError(
                f"Event queue depth limit {self._max_depth} reached.  "
                f"Cannot schedule another event."
            )
        heapq.heappush(self._heap, (event.time, event.seq, event))

    def pop(self) -> SimulationEvent:
        """
        Remove and return the event with the smallest ``(time, seq)``.

        Raises
        ------
        IndexError
            If the queue is empty.
        """
        _, _, event = heapq.heappop(self._heap)
        return event

    def peek_time(self) -> Optional[int]:
        """
        Return the logical time of the next event without removing it,
        or ``None`` if the queue is empty.
        """
        return self._heap[0][0] if self._heap else None

    def is_empty(self) -> bool:
        """Return ``True`` iff the queue contains no events."""
        return not self._heap

    def __len__(self) -> int:
        return len(self._heap)

    def next_seq(self) -> int:
        """
        Allocate and return the next sequence number.

        This must be called *once* per event, immediately before the event
        dataclass is constructed, so that the ``seq`` field embedded in the
        frozen dataclass matches the heap key.
        """
        seq = self._seq
        self._seq += 1
        return seq

    def clear(self) -> None:
        """Reset the queue to an empty state and reset the sequence counter."""
        self._heap.clear()
        self._seq = 0
