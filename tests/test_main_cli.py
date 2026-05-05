import os
import subprocess
import sys
from pathlib import Path
from pansyncer.main import get_version


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def run_cli(*args, cwd=None):
    env = os.environ.copy()
    env["PYTHONPATH"] = str(PROJECT_ROOT)

    return subprocess.run(
        [sys.executable, "-m", "pansyncer.main", *args],
        cwd=cwd or PROJECT_ROOT,
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=5,
    )


def test_cli_help_exits_successfully_and_shows_small_display_option(tmp_path):
    result = run_cli("--help", cwd=tmp_path)

    assert result.returncode == 0
    assert "usage:" in result.stdout.lower()
    assert "--small-display" in result.stdout


def test_cli_version_exits_successfully(tmp_path):
    result = run_cli("--version", cwd=tmp_path)

    assert result.returncode == 0
    assert result.stdout.strip() or result.stderr.strip()


def test_cli_without_radio_device_exits_with_error(tmp_path):
    result = run_cli("-d", "k", "m", cwd=tmp_path)

    assert result.returncode == 1
    assert "You must specify at least one of --devices r|g" in result.stderr


def test_cli_invalid_toml_exits_with_config_error(tmp_path):
    (tmp_path / "pansyncer.toml").write_text(
        """
[main
daemon = true
""",
        encoding="utf-8",
    )

    result = run_cli("--ifreq", "73.095", cwd=tmp_path)

    assert result.returncode == 2
    assert "[CONFIG ERROR]" in result.stderr
    assert "Invalid TOML" in result.stderr

def test_get_version_returns_string():
    value = get_version()

    assert isinstance(value, str)
    assert value