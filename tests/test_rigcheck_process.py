import io
import subprocess

from pansyncer.config import Config
from pansyncer.rigcheck import RigChecker


class FakePopen:
    def __init__(self, args, stdout=None, stderr=None, text=None, bufsize=None, preexec_fn=None):
        self.args = args
        self.stdout = io.StringIO("")
        self.stderr = io.StringIO("")
        self.pid = 12345
        self._returncode = None
        self.wait_calls = []

    def poll(self):
        return self._returncode

    def wait(self, timeout=None):
        self.wait_calls.append(timeout)
        self._returncode = 0
        return 0


class FakeHungPopen(FakePopen):
    def wait(self, timeout=None):
        self.wait_calls.append(timeout)
        if len(self.wait_calls) == 1:
            raise subprocess.TimeoutExpired(self.args, timeout)
        self._returncode = -9
        return -9


def make_cfg(command="rigctld -m 4 -r 127.0.0.1:12345 -t 4532", rig_port=9999):
    cfg = Config()
    cfg.main.daemon = True
    cfg.rigcheck.hamlib_command = command
    cfg.sync.rig_port = rig_port
    return cfg


def test_ensure_rigctld_does_not_start_process_when_port_is_open(monkeypatch):
    cfg = make_cfg()
    checker = RigChecker(cfg, port=cfg.sync.rig_port, display=None, auto_start=True)

    popen_calls = []

    monkeypatch.setattr(checker, "_is_port_open", lambda: True)
    monkeypatch.setattr("subprocess.Popen", lambda *args, **kwargs: popen_calls.append((args, kwargs)))

    try:
        checker._ensure_rigctld()

        assert popen_calls == []
        assert checker._proc is None
    finally:
        checker.cleanup()


def test_ensure_rigctld_does_not_start_process_when_auto_start_is_false(monkeypatch):
    cfg = make_cfg()
    checker = RigChecker(cfg, port=cfg.sync.rig_port, display=None, auto_start=False)

    popen_calls = []

    monkeypatch.setattr(checker, "_is_port_open", lambda: False)
    monkeypatch.setattr("subprocess.Popen", lambda *args, **kwargs: popen_calls.append((args, kwargs)))

    try:
        checker._ensure_rigctld()

        assert popen_calls == []
        assert checker._proc is None
    finally:
        checker.cleanup()


def test_ensure_rigctld_starts_process_with_normalized_configured_port(monkeypatch):
    cfg = make_cfg(
        command="rigctld -m 4 -r 127.0.0.1:12345 --port 1111",
        rig_port=9999,
    )
    checker = RigChecker(cfg, port=cfg.sync.rig_port, display=None, auto_start=True)

    created = []

    def fake_popen(args, **kwargs):
        proc = FakePopen(args, **kwargs)
        created.append((args, kwargs, proc))
        return proc

    monkeypatch.setattr(checker, "_is_port_open", lambda: False)
    monkeypatch.setattr("subprocess.Popen", fake_popen)

    try:
        checker._ensure_rigctld()

        assert len(created) == 1
        args, kwargs, proc = created[0]
        assert args == ["rigctld", "-m", "4", "-r", "127.0.0.1:12345", "-t", "9999"]
        assert kwargs["stdout"] == subprocess.PIPE
        assert kwargs["stderr"] == subprocess.PIPE
        assert kwargs["text"] is True
        assert kwargs["bufsize"] == 1
        assert kwargs["preexec_fn"] is not None
        assert checker._proc is proc
    finally:
        checker.cleanup()


def test_ensure_rigctld_reuses_running_process(monkeypatch):
    cfg = make_cfg()
    checker = RigChecker(cfg, port=cfg.sync.rig_port, display=None, auto_start=True)

    running_proc = FakePopen(["rigctld"])
    checker._proc = running_proc

    popen_calls = []

    monkeypatch.setattr(checker, "_is_port_open", lambda: False)
    monkeypatch.setattr("subprocess.Popen", lambda *args, **kwargs: popen_calls.append((args, kwargs)))

    try:
        checker._ensure_rigctld()

        assert popen_calls == []
        assert checker._proc is running_proc
    finally:
        checker._proc = None
        checker.cleanup()


def test_cleanup_terminates_running_process_group(monkeypatch):
    cfg = make_cfg()
    checker = RigChecker(cfg, port=cfg.sync.rig_port, display=None, auto_start=True)

    proc = FakePopen(["rigctld"])
    checker._proc = proc

    calls = []

    monkeypatch.setattr("os.getpgid", lambda pid: calls.append(("getpgid", pid)) or 777)
    monkeypatch.setattr("os.killpg", lambda pgid, sig: calls.append(("killpg", pgid, sig)))

    checker.cleanup()

    assert checker._proc is None
    assert ("getpgid", 12345) in calls
    assert len([call for call in calls if call[0] == "killpg"]) == 1
    assert proc.wait_calls == [3]


def test_cleanup_kills_process_group_after_terminate_timeout(monkeypatch):
    cfg = make_cfg()
    checker = RigChecker(cfg, port=cfg.sync.rig_port, display=None, auto_start=True)

    proc = FakeHungPopen(["rigctld"])
    checker._proc = proc

    calls = []

    monkeypatch.setattr("os.getpgid", lambda pid: calls.append(("getpgid", pid)) or 777)
    monkeypatch.setattr("os.killpg", lambda pgid, sig: calls.append(("killpg", pgid, sig)))

    checker.cleanup()

    assert checker._proc is None
    assert ("getpgid", 12345) in calls
    kill_calls = [call for call in calls if call[0] == "killpg"]
    assert len(kill_calls) == 2
    assert proc.wait_calls == [3, 1]

def test_ensure_rigctld_rejects_invalid_hamlib_command(monkeypatch):
    cfg = make_cfg(command='rigctld -m 4 -r "broken')
    checker = RigChecker(cfg, port=cfg.sync.rig_port, display=None, auto_start=True)

    popen_calls = []

    monkeypatch.setattr(checker, "_is_port_open", lambda: False)
    monkeypatch.setattr("subprocess.Popen", lambda *args, **kwargs: popen_calls.append((args, kwargs)))

    try:
        assert checker._ensure_rigctld() is False
        assert popen_calls == []
        assert checker._proc is None
    finally:
        checker.cleanup()