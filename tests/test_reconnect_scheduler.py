import threading
import time
from types import SimpleNamespace

from pansyncer.reconnect_scheduler import ReconnectScheduler, SchedulerConfig


class FakeLogger:
    def __init__(self):
        self.messages = []

    def log(self, msg, level="INFO"):
        self.messages.append((level, msg))


def make_scheduler(
    *,
    reconnect_interval=0.01,
    max_workers=2,
    backoff_cap=0.08,
    jitter=0.0,
    slow_threshold=999.0,
):
    cfg = SimpleNamespace(
        reconnect_scheduler=SchedulerConfig(
            reconnect_interval=reconnect_interval,
            max_workers=max_workers,
            backoff_cap=backoff_cap,
            jitter=jitter,
            slow_threshold=slow_threshold,
        )
    )
    logger = FakeLogger()
    scheduler = ReconnectScheduler(cfg, logger)
    return scheduler, logger


def drive_until(scheduler, predicate, *, max_ticks=1000):
    for _ in range(max_ticks):
        scheduler.tick()
        if predicate():
            return
        time.sleep(0.001)

    raise AssertionError("condition was not reached")


def test_registered_task_runs_immediately_and_success_resets_backoff():
    scheduler, _ = make_scheduler()
    calls = []

    def task():
        calls.append("run")
        return True

    try:
        scheduler.register(task, tag="rig", backoff=True)

        drive_until(
            scheduler,
            lambda: len(calls) == 1 and scheduler.tasks[task].future is None,
        )

        rec = scheduler.tasks[task]
        assert rec.tag == "rig"
        assert rec.failures == 0
        assert rec.interval == 0.01
    finally:
        scheduler.shutdown(wait=True)


def test_failed_task_increases_failure_count_and_backoff_interval():
    scheduler, _ = make_scheduler(reconnect_interval=0.01, backoff_cap=0.08)
    calls = []

    def task():
        calls.append("run")
        return False

    try:
        scheduler.register(task, tag="gqrx", backoff=True)

        drive_until(
            scheduler,
            lambda: len(calls) == 1 and scheduler.tasks[task].future is None,
        )

        rec = scheduler.tasks[task]
        assert rec.failures == 1
        assert rec.interval == 0.02
    finally:
        scheduler.shutdown(wait=True)


def test_failed_task_backoff_is_capped():
    scheduler, _ = make_scheduler(reconnect_interval=0.01, backoff_cap=0.02)
    calls = []

    def task():
        calls.append("run")
        return False

    try:
        scheduler.register(task, tag="gqrx", backoff=True)

        drive_until(
            scheduler,
            lambda: len(calls) == 1 and scheduler.tasks[task].future is None,
        )

        first_rec = scheduler.tasks[task]
        first_rec.next_run = time.monotonic()

        drive_until(
            scheduler,
            lambda: len(calls) == 2 and scheduler.tasks[task].future is None,
        )

        rec = scheduler.tasks[task]
        assert rec.failures == 2
        assert rec.interval == 0.02
    finally:
        scheduler.shutdown(wait=True)


def test_task_exception_counts_as_failure_and_is_logged():
    scheduler, logger = make_scheduler()

    def task():
        raise ValueError("boom")

    try:
        scheduler.register(task, tag="rig", backoff=True)

        drive_until(
            scheduler,
            lambda: scheduler.tasks[task].future is None
            and scheduler.tasks[task].failures == 1,
        )

        assert scheduler.tasks[task].interval == 0.02
        assert any("boom" in msg for _, msg in logger.messages)
    finally:
        scheduler.shutdown(wait=True)


def test_non_backoff_task_keeps_base_interval_after_failure():
    scheduler, _ = make_scheduler(reconnect_interval=0.01)
    calls = []

    def task():
        calls.append("run")
        return False

    try:
        scheduler.register(task, tag="mouse", backoff=False)

        drive_until(
            scheduler,
            lambda: len(calls) == 1 and scheduler.tasks[task].future is None,
        )

        rec = scheduler.tasks[task]
        assert rec.failures == 0
        assert rec.interval == 0.01
    finally:
        scheduler.shutdown(wait=True)


def test_unregister_tag_removes_exact_and_prefixed_tags():
    scheduler, _ = make_scheduler()

    def mouse_task():
        return True

    def mouse_extra_task():
        return True

    def rig_task():
        return True

    try:
        scheduler.register(mouse_task, tag="mouse", run_immediately=False)
        scheduler.register(mouse_extra_task, tag="mouse-extra", run_immediately=False)
        scheduler.register(rig_task, tag="rig", run_immediately=False)

        scheduler.unregister_tag("mouse")

        assert mouse_task not in scheduler.tasks
        assert mouse_extra_task not in scheduler.tasks
        assert rig_task in scheduler.tasks
    finally:
        scheduler.shutdown(wait=True)


def test_late_result_from_unregistered_running_task_does_not_restore_task():
    scheduler, _ = make_scheduler()
    release = threading.Event()
    side_effects = []

    def task():
        release.wait(timeout=1.0)
        side_effects.append("worker-finished")
        return True

    try:
        scheduler.register(task, tag="knob")
        scheduler.tick()

        assert task in scheduler.tasks
        assert scheduler.tasks[task].future is not None

        scheduler.unregister_tag("knob")

        assert task not in scheduler.tasks

        release.set()
        scheduler.shutdown(wait=True)

        assert side_effects == ["worker-finished"]
        assert task not in scheduler.tasks
    finally:
        release.set()
        scheduler.shutdown(wait=True)


def test_shutdown_prevents_later_registration():
    scheduler, _ = make_scheduler()
    calls = []

    def task():
        calls.append("run")
        return True

    scheduler.shutdown(wait=True)

    scheduler.register(task, tag="rig")
    scheduler.tick()

    assert calls == []
    assert task not in scheduler.tasks

class ImmediateDoneFuture:
    def __init__(self, result_value=True):
        self.result_value = result_value

    def done(self):
        return True


class BlockingFuture:
    def done(self):
        return False


class FakeExecutor:
    def __init__(self, future):
        self.future = future
        self.submitted = []

    def submit(self, fn, *args):
        self.submitted.append((fn, args))
        return self.future

    def shutdown(self, wait=False):
        pass


def test_tick_drains_old_result_before_starting_new_worker():
    scheduler, _ = make_scheduler(reconnect_interval=10.0)
    calls = []

    def task():
        calls.append("run")
        return True

    try:
        scheduler.register(task, tag="rig", run_immediately=True)

        rec = scheduler.tasks[task]
        old_future = ImmediateDoneFuture()
        new_future = BlockingFuture()

        rec.future = old_future
        rec.next_run = time.monotonic() - 1.0
        scheduler._result_queue.put((task, True, 0.001, rec.generation))
        scheduler.executor = FakeExecutor(new_future)

        scheduler.tick()

        assert scheduler.executor.submitted == []
        assert scheduler.tasks[task].future is None
        assert scheduler.tasks[task].next_run > time.monotonic()

        scheduler.tasks[task].next_run = time.monotonic() - 1.0

        scheduler.tick()

        assert len(scheduler.executor.submitted) == 1
        assert scheduler.tasks[task].future is new_future
    finally:
        scheduler.shutdown(wait=True)