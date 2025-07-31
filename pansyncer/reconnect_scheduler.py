"""
reconnect_scheduler.py
Periodic reconnects attempts may block. So threads are used to execute them.
Main loop (device ) drains a thread-safe result queue each tick to apply timing/backoff decisions.
"""

import time
import random
from dataclasses import dataclass
import concurrent.futures
from queue import Queue, Empty

__all__ = ["SchedulerConfig", "ReconnectScheduler", "TaskRecord"]

@dataclass
class SchedulerConfig:
    """Default configuration"""
    reconnect_interval: float = 3.0
    max_workers: int        = 4
    backoff_cap: float      = 60.0
    jitter: float           = 0.10
    slow_threshold: float   = 1.0

@dataclass                                                                                       ##### Data structure
class TaskRecord:
    def __init__(self, fn=None, tag='', next_run=0.0, interval=0.0, backoff=True,
                 failures=0, future=None, generation=0, last_duration=0.0, pending_result=None):
        self.fn = fn
        self.tag = tag
        self.next_run = next_run
        self.interval = interval
        self.backoff = backoff
        self.failures = failures
        self.future = future
        self.generation = generation
        self.last_duration = last_duration
        self.pending_result = pending_result
                                                                                       ##### Scheduler
class ReconnectScheduler:
    """ Schedule worker threads for periodic connection checks"""
    def __init__(self,
                 cfg,
                 logger,
                 max_workers = 4,
                 backoff_cap = 60.0,
                 jitter = 0.10,
                 slow_threshold = 1.0):
        self.cfg = cfg
        self.logger = logger
        self.reconnect_interval = self.cfg.reconnect_scheduler.reconnect_interval
        self.backoff_cap = backoff_cap
        self.jitter = jitter
        self.slow_threshold = slow_threshold
        self.executor = concurrent.futures.ThreadPoolExecutor(max_workers=max_workers)
        self.tasks = {}
        self.generation = 0
        self._result_queue = Queue()
        self._shutdown = False

                                                                                           ##### Registration / Removal
    def register(self, fn, tag = None, backoff = True, run_immediately = True):
        if self._shutdown:
            return
        if tag is None:
            owner = getattr(fn, '__self__', None)
            tag = owner.__class__.__name__.lower() if owner else fn.__name__
        now = time.monotonic()
        first = now if run_immediately else now + self.reconnect_interval
        rec = self.tasks.get(fn)
        if rec:
            rec.tag = tag
            rec.backoff = backoff
            if run_immediately:
                rec.next_run = now
            return
        self.tasks[fn] = TaskRecord(
            fn=fn,
            tag=tag,
            next_run=first,
            interval=self.reconnect_interval,
            backoff=backoff,
            generation=self.generation,
        )
        self.logger.log(
            f"Scheduler: registered task tag:{tag} interval:{self.reconnect_interval} generation:{self.generation}", "DEBUG")

    def unregister_tag(self, tag):
        self.generation += 1
        to_remove = [fn for fn, rec in self.tasks.items()
                     if rec.tag == tag or rec.tag.startswith(tag)]
        for fn in to_remove:
            self.tasks.pop(fn, None)
        self.logger.log("Scheduler: unregistered %d task(s) for tag '%s'" % (len(to_remove), tag), "DEBUG")

                                                                                           ##### Main Loop Tick
    def tick(self):
        if self._shutdown:
            return
        now = time.monotonic()
        for rec in list(self.tasks.values()):
            if now >= rec.next_run:
                if rec.future is None or rec.future.done():
                    rec.next_run = now + rec.interval
                    rec.future = self.executor.submit(self._worker_wrapper, rec.fn, rec.generation)
        self._drain_results()
                                                                                           ##### Worker and result
    def _worker_wrapper(self, fn, generation):
        start = time.monotonic()
        success = True
        try:
            fn()
        except (OSError, IOError, ValueError, RuntimeError) as e:
            success = False
            self.logger.log("%s error: %s" % (fn.__name__, e), "DEBUG")
        except Exception as e:
            success = False
            self.logger.log("%s unexpected %s: %s" % (fn.__name__, e.__class__.__name__, e), "ERROR")
        finally:
            duration = time.monotonic() - start
            self._result_queue.put((fn, success, duration, generation))                    # Enqueue
        return True

    def _drain_results(self):
        now = time.monotonic()
        while True:
            try:
                fn, success, duration, generation = self._result_queue.get_nowait()
            except Empty:
                break
            rec = self.tasks.get(fn)
            if not rec:
                continue
            if generation != rec.generation:
                continue
            rec.last_duration = duration
            if duration > self.slow_threshold:
                self.logger.log("%s slow %.1fms" % (fn.__name__, duration * 1000.0), "DEBUG")
            if rec.backoff:
                if success:
                    rec.failures = 0
                    rec.interval = self.reconnect_interval
                else:
                    rec.failures += 1
                    rec.interval = min(self.reconnect_interval * (2 ** rec.failures), self.backoff_cap)
                rec.interval *= random.uniform(1 - self.jitter, 1 + self.jitter)
            target = now + rec.interval
            if rec.next_run < target:
                rec.next_run = target
            rec.future = None
                                                                                           ##### Diagnostics
    def debug_status(self):
        now = time.monotonic()
        lines = []
        for rec in self.tasks.values():
            eta = rec.next_run - now
            running = rec.future is not None and not rec.future.done()
            lines.append("%s tag=%s run_in=%6.2fs int=%5.2fs fail=%d run=%s dur=%6.1fms" % (
                rec.fn.__name__, rec.tag, eta, rec.interval, rec.failures,
                'Y' if running else 'N', rec.last_duration * 1000.0))
        return lines
                                                                                          ##### Shutdown
    def shutdown(self, wait = False):
        if self._shutdown:
            return
        self._shutdown = True
        try:
            self.executor.shutdown(wait=wait)
        except Exception as e:
            self.logger.log("Scheduler shutdown error: %s" % e, "ERROR")
