import threading
import time
from pansyncer.config import Config
from pansyncer.device_handler import DeviceHandler
from pansyncer.device_register import DeviceRegister


class FakeLogger:
    def __init__(self):
        self.messages = []

    def log(self, msg, level="INFO"):
        self.messages.append((level, msg))


class FakeScheduler:
    def __init__(self, events):
        self.events = events

    def shutdown(self, wait=False):
        self.events.append(("scheduler.shutdown", wait))


class FakeRigChecker:
    def __init__(self, events):
        self.events = events

    def cleanup(self):
        self.events.append(("rigchk.cleanup", None))


class FakeKnob:
    def __init__(self, events):
        self.events = events

    def disconnect(self):
        self.events.append(("knob.disconnect", None))


class FakeMouse:
    def __init__(self, events):
        self.events = events

    def disconnect(self):
        self.events.append(("mouse.disconnect", None))


def make_handler_without_devices():
    cfg = Config()
    cfg.main.daemon = True
    cfg.devices.enabled = []

    devices = DeviceRegister(cfg)
    logger = FakeLogger()

    handler = DeviceHandler(
        cfg=cfg,
        is_tty=False,
        devices=devices,
        logger=logger,
        sync=None,
        step=None,
        display=None,
        keyboard=None,
    )

    return handler


def test_device_handler_cleanup_waits_for_scheduler_before_closing_devices():
    events = []
    handler = make_handler_without_devices()

    handler.scheduler = FakeScheduler(events)
    handler._rigchk = FakeRigChecker(events)
    handler._knob = FakeKnob(events)
    handler._mouse = FakeMouse(events)

    handler.cleanup()

    assert events == [
        ("scheduler.shutdown", True),
        ("rigchk.cleanup", None),
        ("knob.disconnect", None),
        ("mouse.disconnect", None),
    ]

    assert handler._rigchk is None
    assert handler._knob is None
    assert handler._mouse is None

class FakeBlockingKnob:
    def __init__(self, events, started, release):
        self.events = events
        self.started = started
        self.release = release

    def ensure_connected(self):
        self.events.append(("knob.ensure_connected.start", None))
        self.started.set()
        self.release.wait(timeout=1.0)
        self.events.append(("knob.ensure_connected.end", None))
        return True

    def disconnect(self):
        self.events.append(("knob.disconnect", None))


class FakeTagScheduler:
    def __init__(self, events):
        self.events = events

    def unregister_tag(self, tag):
        self.events.append(("scheduler.unregister_tag", tag))


def test_knob_remove_waits_for_running_reconnect_before_disconnect():
    events = []
    started = threading.Event()
    release = threading.Event()

    handler = make_handler_without_devices()
    handler.scheduler = FakeTagScheduler(events)
    handler.devices._devices.add("knob")
    handler._knob = FakeBlockingKnob(events, started, release)

    worker = threading.Thread(target=handler._ensure_knob_connected)
    worker.start()

    assert started.wait(timeout=1.0)

    remove_done = threading.Event()

    def remove_knob():
        handler._on_knob_removed("knob")
        remove_done.set()

    remover = threading.Thread(target=remove_knob)
    remover.start()

    time.sleep(0.01)

    assert not remove_done.is_set()

    release.set()
    worker.join(timeout=1.0)
    remover.join(timeout=1.0)

    assert remove_done.is_set()
    assert events == [
        ("knob.ensure_connected.start", None),
        ("knob.ensure_connected.end", None),
        ("scheduler.unregister_tag", "knob"),
        ("knob.disconnect", None),
    ]
    assert handler._knob is None


def test_knob_reconnect_wrapper_does_nothing_when_knob_is_disabled():
    events = []
    started = threading.Event()
    release = threading.Event()

    handler = make_handler_without_devices()
    handler.devices._devices.discard("knob")
    handler._knob = FakeBlockingKnob(events, started, release)

    assert handler._ensure_knob_connected() is False
    assert events == []

def test_device_handler_cleanup_waits_for_lifecycle_lock_before_closing_devices():
    events = []
    handler = make_handler_without_devices()

    handler.scheduler = FakeScheduler(events)
    handler._knob = FakeKnob(events)

    handler._lifecycle_lock.acquire()

    cleanup_done = threading.Event()

    def run_cleanup():
        handler.cleanup()
        cleanup_done.set()

    worker = threading.Thread(target=run_cleanup)
    worker.start()

    try:
        for _ in range(100):
            if ("scheduler.shutdown", True) in events:
                break
            time.sleep(0.001)

        assert ("scheduler.shutdown", True) in events
        assert ("knob.disconnect", None) not in events
        assert not cleanup_done.is_set()
    finally:
        handler._lifecycle_lock.release()

    worker.join(timeout=1.0)

    assert cleanup_done.is_set()
    assert events == [
        ("scheduler.shutdown", True),
        ("knob.disconnect", None),
    ]
    assert handler._knob is None

class FakeBlockingMouse:
    def __init__(self, events, started, release):
        self.events = events
        self.started = started
        self.release = release

    def ensure_connected(self):
        self.events.append(("mouse.ensure_connected.start", None))
        self.started.set()
        self.release.wait(timeout=1.0)
        self.events.append(("mouse.ensure_connected.end", None))
        return True

    def disconnect(self):
        self.events.append(("mouse.disconnect", None))


class FakeBlockingRigChecker:
    def __init__(self, events, started, release):
        self.events = events
        self.started = started
        self.release = release

    def check_rig(self):
        self.events.append(("rigchk.check_rig.start", None))
        self.started.set()
        self.release.wait(timeout=1.0)
        self.events.append(("rigchk.check_rig.end", None))
        return True

    def cleanup(self):
        self.events.append(("rigchk.cleanup", None))


class FakeSync:
    def __init__(self, events):
        self.events = events

    def shutdown(self, role=None):
        self.events.append(("sync.shutdown", role))


def test_mouse_remove_waits_for_running_reconnect_before_disconnect():
    events = []
    started = threading.Event()
    release = threading.Event()

    handler = make_handler_without_devices()
    handler.scheduler = FakeTagScheduler(events)
    handler.devices._devices.add("mouse")
    handler._mouse = FakeBlockingMouse(events, started, release)

    worker = threading.Thread(target=handler._ensure_mouse_connected)
    worker.start()

    assert started.wait(timeout=1.0)

    remove_done = threading.Event()

    def remove_mouse():
        handler._on_mouse_removed("mouse")
        remove_done.set()

    remover = threading.Thread(target=remove_mouse)
    remover.start()

    time.sleep(0.01)

    assert not remove_done.is_set()

    release.set()
    worker.join(timeout=1.0)
    remover.join(timeout=1.0)

    assert remove_done.is_set()
    assert events == [
        ("mouse.ensure_connected.start", None),
        ("mouse.ensure_connected.end", None),
        ("scheduler.unregister_tag", "mouse"),
        ("mouse.disconnect", None),
    ]
    assert handler._mouse is None


def test_mouse_reconnect_wrapper_does_nothing_when_mouse_is_disabled():
    events = []
    started = threading.Event()
    release = threading.Event()

    handler = make_handler_without_devices()
    handler.devices._devices.discard("mouse")
    handler._mouse = FakeBlockingMouse(events, started, release)

    assert handler._ensure_mouse_connected() is False
    assert events == []


def test_rig_remove_waits_for_running_check_before_cleanup():
    events = []
    started = threading.Event()
    release = threading.Event()

    handler = make_handler_without_devices()
    handler.scheduler = FakeTagScheduler(events)
    handler.sync = FakeSync(events)
    handler.devices._devices.add("rig")
    handler._rigchk = FakeBlockingRigChecker(events, started, release)

    worker = threading.Thread(target=handler._check_rig_connected)
    worker.start()

    assert started.wait(timeout=1.0)

    remove_done = threading.Event()

    def remove_rig():
        handler._on_rig_removed("rig")
        remove_done.set()

    remover = threading.Thread(target=remove_rig)
    remover.start()

    time.sleep(0.01)

    assert not remove_done.is_set()

    release.set()
    worker.join(timeout=1.0)
    remover.join(timeout=1.0)

    assert remove_done.is_set()
    assert events == [
        ("rigchk.check_rig.start", None),
        ("rigchk.check_rig.end", None),
        ("scheduler.unregister_tag", "rig"),
        ("sync.shutdown", "rig"),
        ("rigchk.cleanup", None),
    ]
    assert handler._rigchk is None


def test_rig_reconnect_wrapper_does_nothing_when_rig_is_disabled():
    events = []
    started = threading.Event()
    release = threading.Event()

    handler = make_handler_without_devices()
    handler.devices._devices.discard("rig")
    handler._rigchk = FakeBlockingRigChecker(events, started, release)

    assert handler._check_rig_connected() is False
    assert events == []