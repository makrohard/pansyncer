from pansyncer.config import Config
from pansyncer.device_handler import DeviceHandler
from pansyncer.device_register import DeviceRegister


class FakeLogger:
    def __init__(self):
        self.messages = []

    def log(self, msg, level="INFO"):
        self.messages.append((level, msg))


class FakeScheduler:
    def __init__(self):
        self.register_calls = []

    def register(self, fn, **kwargs):
        self.register_calls.append((fn, kwargs))

    def shutdown(self, wait=False):
        pass


class FakeKnobController:
    def __init__(self, cfg, logger, display=None):
        self.cfg = cfg
        self.logger = logger
        self.display = display

    def ensure_connected(self):
        return False

    def disconnect(self):
        pass


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


def test_knob_scheduler_uses_input_hotplug_config(monkeypatch):
    handler = make_handler_without_devices()
    handler.devices._devices.add("knob")
    handler.cfg.input_hotplug.watchdog_interval = 8.0
    handler.cfg.input_hotplug.watchdog_backoff_cap = 80.0
    handler.scheduler = FakeScheduler()

    monkeypatch.setattr("pansyncer.device_handler.KnobController", FakeKnobController)

    _ = handler.knob

    assert len(handler.scheduler.register_calls) == 1
    _fn, kwargs = handler.scheduler.register_calls[0]
    assert kwargs["tag"] == "knob"
    assert kwargs["interval"] == 8.0
    assert kwargs["backoff_cap"] == 80.0
    assert kwargs["run_immediately"] is False


def test_hotplug_retry_uses_input_hotplug_config():
    handler = make_handler_without_devices()
    handler.cfg.input_hotplug.retry_delay = 0.75

    calls = []

    class FakeSchedulerWithTrigger:
        def trigger_tag(self, tag, delay=0.0):
            calls.append((tag, delay))
            return 1

    handler.scheduler = FakeSchedulerWithTrigger()

    assert handler._trigger_input_retry("knob") == 1
    assert calls == [("knob", 0.75)]


def test_hotplug_monitor_not_started_when_disabled(monkeypatch):
    handler = make_handler_without_devices()
    handler.cfg.input_hotplug.enabled = False

    def fail_monitor(*args, **kwargs):
        raise AssertionError("monitor must not be created when input_hotplug.enabled is false")

    monkeypatch.setattr("pansyncer.device_handler.EvdevHotplugMonitor", fail_monitor)

    assert handler._ensure_input_hotplug_monitor() is None
    assert handler._input_hotplug is None