from __future__ import annotations

import threading
import time
import unittest
from collections import Counter

from repository_analysis.contracts import PairOutcome, PairStatus, PairWorkItem
from repository_analysis.coordinator import (
    CoordinatorStats,
    WorkerExecutionError,
    run_pairs,
)


def work_items(count: int) -> list[PairWorkItem]:
    return [
        PairWorkItem(
            sequence=sequence,
            old_commit=f"old-{sequence}",
            new_commit=f"new-{sequence}",
            fingerprint=f"fingerprint-{sequence}",
        )
        for sequence in range(count)
    ]


def completed(item: PairWorkItem) -> PairOutcome:
    return PairOutcome(work_item=item, status=PairStatus.COMPLETED)


class RunPairsTests(unittest.TestCase):
    def test_slow_early_pair_does_not_prevent_dynamic_claiming(self) -> None:
        release_first = threading.Event()
        later_progress = threading.Event()
        completed_later: list[int] = []
        worker_claims: dict[str, list[int]] = {}
        lock = threading.Lock()

        def execute(item: PairWorkItem) -> PairOutcome:
            name = threading.current_thread().name
            with lock:
                worker_claims.setdefault(name, []).append(item.sequence)
            if item.sequence == 0:
                release_first.wait()
            else:
                with lock:
                    completed_later.append(item.sequence)
                    if len(completed_later) >= 5:
                        later_progress.set()
            return completed(item)

        published: list[int] = []
        run_error: list[BaseException] = []

        def run() -> None:
            try:
                run_pairs(
                    work_items(8),
                    execute,
                    lambda outcome: published.append(outcome.work_item.sequence),
                    worker_count=3,
                    work_queue_capacity=2,
                    outcome_capacity=8,
                )
            except BaseException as error:
                run_error.append(error)

        coordinator_thread = threading.Thread(target=run)
        coordinator_thread.start()
        try:
            self.assertTrue(later_progress.wait(timeout=10))
        finally:
            release_first.set()
        coordinator_thread.join(timeout=10)

        self.assertFalse(coordinator_thread.is_alive())
        self.assertEqual(run_error, [])
        self.assertGreaterEqual(len(completed_later), 5)
        self.assertTrue(any(len(claims) > 1 for claims in worker_claims.values()))
        self.assertEqual(published, list(range(8)))

    def test_worker_count_is_fixed_and_each_item_executes_once(self) -> None:
        worker_count = 4
        first_claims = threading.Barrier(worker_count)
        claims: Counter[int] = Counter()
        worker_names: set[str] = set()
        lock = threading.Lock()

        def execute(item: PairWorkItem) -> PairOutcome:
            with lock:
                claims[item.sequence] += 1
                worker_names.add(threading.current_thread().name)
            if item.sequence < worker_count:
                first_claims.wait(timeout=10)
            return completed(item)

        stats = run_pairs(
            work_items(40),
            execute,
            lambda outcome: None,
            worker_count=worker_count,
        )

        self.assertEqual(stats.worker_count, worker_count)
        self.assertEqual(len(worker_names), worker_count)
        self.assertEqual(claims, Counter({sequence: 1 for sequence in range(40)}))
        self.assertEqual(stats.submitted_count, 40)
        self.assertEqual(stats.completed_count, 40)
        self.assertEqual(stats.published_count, 40)
        self.assertFalse(
            any(
                thread.name.startswith("repository-analysis-worker-")
                for thread in threading.enumerate()
            )
        )

    def test_completion_can_be_out_of_order_but_publication_is_ordered(self) -> None:
        release_first = threading.Event()
        second_completed = threading.Event()
        completion_order: list[int] = []
        publication_order: list[int] = []
        lock = threading.Lock()

        def execute(item: PairWorkItem) -> PairOutcome:
            if item.sequence == 0:
                release_first.wait()
            with lock:
                completion_order.append(item.sequence)
            if item.sequence == 1:
                second_completed.set()
            return completed(item)

        def release_after_second() -> None:
            second_completed.wait(timeout=10)
            release_first.set()

        release_thread = threading.Thread(target=release_after_second)
        release_thread.start()
        run_pairs(
            work_items(4),
            execute,
            lambda outcome: publication_order.append(outcome.work_item.sequence),
            worker_count=2,
            outcome_capacity=4,
        )
        release_thread.join(timeout=10)

        self.assertTrue(second_completed.is_set())
        self.assertLess(completion_order.index(1), completion_order.index(0))
        self.assertEqual(publication_order, [0, 1, 2, 3])

    def test_work_and_unpublished_outcome_bounds_apply(self) -> None:
        release_first = threading.Event()
        second_completed = threading.Event()
        third_started = threading.Event()

        def execute(item: PairWorkItem) -> PairOutcome:
            if item.sequence == 0:
                release_first.wait()
            elif item.sequence == 1:
                second_completed.set()
            elif item.sequence == 2:
                third_started.set()
            return completed(item)

        stats_result: list[CoordinatorStats] = []

        def run() -> None:
            stats_result.append(
                run_pairs(
                    work_items(6),
                    execute,
                    lambda outcome: None,
                    worker_count=2,
                    work_queue_capacity=1,
                    outcome_capacity=2,
                )
            )

        coordinator_thread = threading.Thread(target=run)
        coordinator_thread.start()
        try:
            self.assertTrue(second_completed.wait(timeout=10))
            self.assertFalse(third_started.wait(timeout=0.2))
        finally:
            release_first.set()
        coordinator_thread.join(timeout=10)

        self.assertFalse(coordinator_thread.is_alive())
        stats = stats_result[0]
        self.assertLessEqual(stats.max_queued_work, 1)
        self.assertEqual(stats.max_unpublished_outcomes, 2)

    def test_worker_error_stops_safely_and_propagates(self) -> None:
        published: list[int] = []
        result: list[BaseException] = []

        def execute(item: PairWorkItem) -> PairOutcome:
            if item.sequence == 2:
                raise RuntimeError("injected failure")
            time.sleep(0.01)
            return completed(item)

        def run() -> None:
            try:
                run_pairs(
                    work_items(100),
                    execute,
                    lambda outcome: published.append(outcome.work_item.sequence),
                    worker_count=3,
                    work_queue_capacity=2,
                    outcome_capacity=3,
                )
            except BaseException as error:
                result.append(error)

        coordinator_thread = threading.Thread(target=run)
        coordinator_thread.start()
        coordinator_thread.join(timeout=10)

        self.assertFalse(coordinator_thread.is_alive(), "coordinator deadlocked")
        self.assertEqual(len(result), 1)
        self.assertIsInstance(result[0], WorkerExecutionError)
        self.assertIsInstance(result[0].cause, RuntimeError)
        self.assertEqual(result[0].work_item.sequence, 2)
        self.assertFalse(
            any(
                thread.name.startswith("repository-analysis-worker-")
                for thread in threading.enumerate()
            )
        )

    def test_acknowledgement_requires_successful_publication(self) -> None:
        events: list[tuple[str, int]] = []

        def publish(outcome: PairOutcome) -> None:
            events.append(("publish", outcome.work_item.sequence))
            if outcome.work_item.sequence == 1:
                raise RuntimeError("injected publication failure")

        def acknowledge(outcome: PairOutcome) -> None:
            events.append(("acknowledge", outcome.work_item.sequence))

        with self.assertRaisesRegex(RuntimeError, "publication failure"):
            run_pairs(
                work_items(3),
                completed,
                publish,
                worker_count=1,
                acknowledge_pair=acknowledge,
            )

        self.assertEqual(
            events,
            [("publish", 0), ("acknowledge", 0), ("publish", 1)],
        )


if __name__ == "__main__":
    unittest.main()
