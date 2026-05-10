import struct

from pansyncer.evdev_hotplug import (
    EvdevHotplugMonitor,
    IN_CREATE,
    IN_DELETE,
    IN_Q_OVERFLOW,
)


def raw_event(name, mask):
    encoded = name.encode() + b"\0"
    return struct.pack("iIII", 1, mask, 0, len(encoded)) + encoded


def test_parse_events_returns_name_and_action():
    events = EvdevHotplugMonitor._parse_events(
        raw_event("event10", IN_CREATE) + raw_event("event11", IN_DELETE)
    )

    assert [(event.name, event.action) for event in events] == [
        ("event10", "add"),
        ("event11", "remove"),
    ]


def test_relevant_event_accepts_event_nodes_and_overflow():
    event_node = EvdevHotplugMonitor._parse_events(raw_event("event12", IN_CREATE))[0]
    js_node = EvdevHotplugMonitor._parse_events(raw_event("js0", IN_CREATE))[0]
    overflow = EvdevHotplugMonitor._parse_events(raw_event("", IN_Q_OVERFLOW))[0]

    assert EvdevHotplugMonitor.is_relevant_event(event_node) is True
    assert EvdevHotplugMonitor.is_relevant_event(js_node) is False
    assert EvdevHotplugMonitor.is_relevant_event(overflow) is True


from pansyncer.evdev_hotplug import InputHotplugConfig


class FakeLogger:
    def __init__(self):
        self.messages = []

    def log(self, msg, level="INFO"):
        self.messages.append((level, msg))


def test_monitor_disabled_by_config_does_not_start():
    logger = FakeLogger()
    monitor = EvdevHotplugMonitor(logger, InputHotplugConfig(enabled=False, path="/tmp/nope"))

    assert monitor.active() is False
    assert monitor.fd() is None
    assert any("disabled by config" in msg for _, msg in logger.messages)


def test_monitor_uses_configured_path_when_path_is_missing():
    logger = FakeLogger()
    monitor = EvdevHotplugMonitor(logger, InputHotplugConfig(path="/tmp/pansyncer-missing-input-dir"))

    assert monitor.path == "/tmp/pansyncer-missing-input-dir"
    assert monitor.active() is False
    assert any("/tmp/pansyncer-missing-input-dir" in msg for _, msg in logger.messages)