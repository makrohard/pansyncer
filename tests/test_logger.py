import logging

from pansyncer.logger import Logger


class FakeDisplay:
    def __init__(self):
        self.lines = []

    def log(self, text):
        self.lines.append(text)


def test_logger_writes_info_to_display():
    display = FakeDisplay()
    logger = Logger("test_logger_display_info", display=display, level="INFO")

    try:
        logger.log("hello", "INFO")

        assert display.lines == ["[INFO] hello"]
    finally:
        logger.close()


def test_logger_respects_log_level_for_display():
    display = FakeDisplay()
    logger = Logger("test_logger_display_level", display=display, level="WARNING")

    try:
        logger.log("hidden", "INFO")
        logger.log("shown", "WARNING")

        assert display.lines == ["[WARNING] shown"]
    finally:
        logger.close()


def test_logger_without_display_writes_warning_to_stderr(capsys):
    logger = Logger("test_logger_stderr_warning", display=None, level="INFO")

    try:
        logger.log("warn me", "WARNING")

        captured = capsys.readouterr()
        assert "[PANSYNCER ERROR]: [WARNING] warn me" in captured.err
        assert captured.out == ""
    finally:
        logger.close()


def test_logger_without_display_does_not_write_info_to_stderr(capsys):
    logger = Logger("test_logger_stderr_info", display=None, level="INFO")

    try:
        logger.log("info only", "INFO")

        captured = capsys.readouterr()
        assert captured.err == ""
        assert captured.out == ""
    finally:
        logger.close()


def test_logger_writes_to_file(tmp_path):
    path = tmp_path / "pansyncer.log"
    display = FakeDisplay()
    logger = Logger(
        "test_logger_file",
        display=display,
        level="INFO",
        logfile_path=str(path),
    )

    try:
        logger.log("file line", "INFO")
    finally:
        logger.close()

    assert "[INFO] file line" in path.read_text(encoding="utf-8")


def test_logger_reports_file_open_error_to_display(tmp_path):
    display = FakeDisplay()
    directory_path = tmp_path / "not_a_file"
    directory_path.mkdir()

    logger = Logger(
        "test_logger_file_error",
        display=display,
        level="INFO",
        logfile_path=str(directory_path),
    )

    try:
        assert any("[LOGGER ERROR] Failed to write log file:" in line for line in display.lines)
    finally:
        logger.close()


def test_recreating_logger_with_same_name_replaces_old_handlers():
    name = "test_logger_recreate_same_name"

    first_display = FakeDisplay()
    first = Logger(name, display=first_display, level="INFO")
    first.log("first", "INFO")

    second_display = FakeDisplay()
    second = Logger(name, display=second_display, level="INFO")
    second.log("second", "INFO")

    try:
        assert first_display.lines == ["[INFO] first"]
        assert second_display.lines == ["[INFO] second"]

        raw_logger = logging.getLogger(name)
        assert len(raw_logger.handlers) == 1
    finally:
        second.close()


def test_close_removes_all_handlers():
    name = "test_logger_close_removes_handlers"
    logger = Logger(name, display=FakeDisplay(), level="INFO")

    raw_logger = logging.getLogger(name)
    assert raw_logger.handlers

    logger.close()

    assert raw_logger.handlers == []

def test_logger_invalid_log_level_falls_back_to_info():
    display = FakeDisplay()
    logger = Logger("test_logger_invalid_level", display=display, level="DEBUGG")

    try:
        logger.log("still works", "INFO")

        assert display.lines == ["[INFO] still works"]
    finally:
        logger.close()

def test_logger_is_enabled_returns_true_for_active_level():
    logger = Logger("test_logger_is_enabled_true", level="DEBUG")

    try:
        assert logger.is_enabled("DEBUG") is True
        assert logger.is_enabled("INFO") is True
    finally:
        logger.close()


def test_logger_is_enabled_returns_false_for_inactive_level():
    logger = Logger("test_logger_is_enabled_false", level="WARNING")

    try:
        assert logger.is_enabled("DEBUG") is False
        assert logger.is_enabled("INFO") is False
        assert logger.is_enabled("WARNING") is True
    finally:
        logger.close()