"""Bounded dynamic scheduling with deterministic pair publication."""

from __future__ import annotations

import queue
import threading
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import TypeAlias

from .contracts import PairOutcome, PairWorkItem


PairExecutor: TypeAlias = Callable[[PairWorkItem], PairOutcome]
PairPublisher: TypeAlias = Callable[[PairOutcome], None]
PairAcknowledger: TypeAlias = Callable[[PairOutcome], None]


@dataclass(frozen=True, slots=True)
class CoordinatorStats:
    """Constant-size observations from one completed scheduling run."""

    worker_count: int
    submitted_count: int
    completed_count: int
    published_count: int
    max_queued_work: int
    max_unpublished_outcomes: int


class WorkerExecutionError(RuntimeError):
    """An injected pair executor failed unexpectedly inside a worker."""

    def __init__(self, work_item: PairWorkItem, cause: BaseException) -> None:
        super().__init__(
            f"worker failed while executing pair {work_item.sequence}: {cause}"
        )
        self.work_item = work_item
        self.cause = cause


@dataclass(frozen=True, slots=True)
class _WorkerResult:
    work_item: PairWorkItem
    outcome: PairOutcome | None = None
    error: BaseException | None = None


def run_pairs(
    work_items: Iterable[PairWorkItem],
    execute_pair: PairExecutor,
    publish_pair: PairPublisher,
    *,
    worker_count: int,
    work_queue_capacity: int | None = None,
    outcome_capacity: int | None = None,
    acknowledge_pair: PairAcknowledger | None = None,
) -> CoordinatorStats:
    """Execute, publish, and optionally acknowledge each pair in order.

    An acknowledgement runs only after publication returns successfully. It is
    the ownership boundary that permits an executor to remove ephemeral inputs.
    """

    work_capacity, pending_capacity = _validated_capacities(
        worker_count, work_queue_capacity, outcome_capacity
    )
    work_queue: queue.Queue[PairWorkItem] = queue.Queue(maxsize=work_capacity)
    result_queue: queue.Queue[_WorkerResult] = queue.Queue(
        maxsize=pending_capacity
    )
    orchestration_errors: queue.Queue[BaseException] = queue.Queue()
    outcome_slots = threading.Semaphore(pending_capacity)
    stop_event = threading.Event()

    workers = [
        threading.Thread(
            target=_worker_loop,
            name=f"repository-analysis-worker-{worker_number}",
            args=(
                work_queue,
                result_queue,
                orchestration_errors,
                outcome_slots,
                stop_event,
                execute_pair,
            ),
        )
        for worker_number in range(worker_count)
    ]
    for worker in workers:
        worker.start()

    iterator = iter(work_items)
    next_item: PairWorkItem | None = None
    input_exhausted = False
    expected_submission = 0
    next_publication = 0
    submitted_count = 0
    completed_count = 0
    published_count = 0
    unpublished_count = 0
    max_queued_work = 0
    max_unpublished_outcomes = 0
    pending: dict[int, PairOutcome] = {}
    failure: BaseException | None = None

    try:
        while True:
            try:
                orchestration_error = orchestration_errors.get_nowait()
            except queue.Empty:
                pass
            else:
                raise orchestration_error

            while not input_exhausted and not stop_event.is_set():
                if next_item is None:
                    try:
                        next_item = next(iterator)
                    except StopIteration:
                        input_exhausted = True
                        break
                    if next_item.sequence != expected_submission:
                        raise ValueError(
                            "pair sequences must be contiguous and start at zero; "
                            f"expected {expected_submission}, "
                            f"got {next_item.sequence}"
                        )

                try:
                    work_queue.put_nowait(next_item)
                except queue.Full:
                    break
                submitted_count += 1
                expected_submission += 1
                next_item = None
                max_queued_work = max(max_queued_work, work_queue.qsize())

            if input_exhausted and completed_count == submitted_count and not pending:
                break

            try:
                result = result_queue.get(timeout=0.1)
            except queue.Empty:
                continue
            completed_count += 1
            unpublished_count += 1
            max_unpublished_outcomes = max(
                max_unpublished_outcomes, unpublished_count
            )

            if result.error is not None:
                outcome_slots.release()
                unpublished_count -= 1
                raise WorkerExecutionError(result.work_item, result.error)

            assert result.outcome is not None
            pending[result.work_item.sequence] = result.outcome
            while next_publication in pending:
                outcome = pending.pop(next_publication)
                try:
                    publish_pair(outcome)
                    if acknowledge_pair is not None:
                        acknowledge_pair(outcome)
                finally:
                    unpublished_count -= 1
                    outcome_slots.release()
                published_count += 1
                next_publication += 1
    except BaseException as error:
        failure = error
        stop_event.set()
    finally:
        stop_event.set()
        for _ in pending.values():
            outcome_slots.release()
        pending.clear()
        _drain_and_join(workers, result_queue, outcome_slots)
        if failure is None:
            try:
                failure = orchestration_errors.get_nowait()
            except queue.Empty:
                pass

    if failure is not None:
        raise failure

    return CoordinatorStats(
        worker_count=worker_count,
        submitted_count=submitted_count,
        completed_count=completed_count,
        published_count=published_count,
        max_queued_work=max_queued_work,
        max_unpublished_outcomes=max_unpublished_outcomes,
    )


def _validated_capacities(
    worker_count: int,
    work_queue_capacity: int | None,
    outcome_capacity: int | None,
) -> tuple[int, int]:
    if worker_count <= 0:
        raise ValueError("worker_count must be positive")
    work_capacity = (
        worker_count if work_queue_capacity is None else work_queue_capacity
    )
    pending_capacity = (
        worker_count * 2 if outcome_capacity is None else outcome_capacity
    )
    if work_capacity <= 0:
        raise ValueError("work_queue_capacity must be positive")
    if pending_capacity < worker_count:
        raise ValueError("outcome_capacity must be at least worker_count")
    return work_capacity, pending_capacity


def _worker_loop(
    work_queue: queue.Queue[PairWorkItem],
    result_queue: queue.Queue[_WorkerResult],
    orchestration_errors: queue.Queue[BaseException],
    outcome_slots: threading.Semaphore,
    stop_event: threading.Event,
    execute_pair: PairExecutor,
) -> None:
    try:
        open_worker = getattr(execute_pair, "open_worker", None)
        if open_worker is not None:
            with open_worker() as worker_execute_pair:
                _execute_worker_items(
                    work_queue,
                    result_queue,
                    outcome_slots,
                    stop_event,
                    worker_execute_pair,
                )
            return
        _execute_worker_items(
            work_queue,
            result_queue,
            outcome_slots,
            stop_event,
            execute_pair,
        )
    except BaseException as error:
        stop_event.set()
        orchestration_errors.put(error)


def _execute_worker_items(
    work_queue: queue.Queue[PairWorkItem],
    result_queue: queue.Queue[_WorkerResult],
    outcome_slots: threading.Semaphore,
    stop_event: threading.Event,
    execute_pair: PairExecutor,
) -> None:
    while not stop_event.is_set():
        acquired_slot = False
        work_item: PairWorkItem | None = None
        try:
            while not stop_event.is_set():
                if outcome_slots.acquire(timeout=0.05):
                    acquired_slot = True
                    break
            if not acquired_slot:
                return

            while not stop_event.is_set():
                try:
                    work_item = work_queue.get(timeout=0.05)
                    break
                except queue.Empty:
                    continue
            if work_item is None:
                return

            try:
                outcome = execute_pair(work_item)
                if outcome.work_item != work_item:
                    raise ValueError(
                        "pair executor returned an outcome for another item"
                    )
                result = _WorkerResult(work_item=work_item, outcome=outcome)
            except BaseException as error:
                result = _WorkerResult(work_item=work_item, error=error)

            while True:
                try:
                    result_queue.put(result, timeout=0.05)
                    acquired_slot = False
                    break
                except queue.Full:
                    continue
        finally:
            if acquired_slot:
                outcome_slots.release()
            if work_item is not None:
                work_queue.task_done()


def _drain_and_join(
    workers: list[threading.Thread],
    result_queue: queue.Queue[_WorkerResult],
    outcome_slots: threading.Semaphore,
) -> None:
    while any(worker.is_alive() for worker in workers):
        try:
            result_queue.get(timeout=0.05)
        except queue.Empty:
            continue
        outcome_slots.release()

    while True:
        try:
            result_queue.get_nowait()
        except queue.Empty:
            break
        outcome_slots.release()

    for worker in workers:
        worker.join()
