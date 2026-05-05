import time

from pansyncer.main import PanSyncer


class FakeDeviceHandler:
    def tick(self, now):
        raise KeyboardInterrupt


class FakeSync:
    def tick(self, now):
        raise AssertionError("sync.tick should not be called after KeyboardInterrupt")


class FakeDisplay:
    def __init__(self):
        self.logs = []
        self.draws = []

    def log(self, text):
        self.logs.append(text)

    def draw(self, now):
        self.draws.append(now)

    def check_resize(self, now):
        raise AssertionError("check_resize should not be called after KeyboardInterrupt")


def test_main_loop_logs_quit_message_on_keyboard_interrupt(monkeypatch):
    app = PanSyncer.__new__(PanSyncer)
    app.device_handler = FakeDeviceHandler()
    app.sync = FakeSync()
    app.display = FakeDisplay()

    monkeypatch.setattr(time, "monotonic", lambda: 10.0)

    app.main_loop()

    assert app.display.logs == ["[QUIT] shutting down..."]
    assert app.display.draws == [10.0]