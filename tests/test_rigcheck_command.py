from pansyncer.rigcheck import RigChecker


def test_set_rigctld_port_replaces_short_port_option():
    args = ["rigctld", "-m", "4", "-r", "127.0.0.1:12345", "-t", "4532"]

    result = RigChecker._set_rigctld_port(args, 9999)

    assert result == ["rigctld", "-m", "4", "-r", "127.0.0.1:12345", "-t", "9999"]


def test_set_rigctld_port_replaces_joined_short_port_option():
    args = ["rigctld", "-m", "4", "-t4532", "-r", "127.0.0.1:12345"]

    result = RigChecker._set_rigctld_port(args, 9999)

    assert result == ["rigctld", "-m", "4", "-r", "127.0.0.1:12345", "-t", "9999"]


def test_set_rigctld_port_replaces_long_port_option():
    args = ["rigctld", "--port", "4532", "-m", "4"]

    result = RigChecker._set_rigctld_port(args, 9999)

    assert result == ["rigctld", "-m", "4", "-t", "9999"]


def test_set_rigctld_port_replaces_long_equals_port_option():
    args = ["rigctld", "--port=4532", "-m", "4"]

    result = RigChecker._set_rigctld_port(args, 9999)

    assert result == ["rigctld", "-m", "4", "-t", "9999"]


def test_set_rigctld_port_replaces_long_port_option_at_end():
    args = ["rigctld", "-m", "4", "--port", "4532"]

    result = RigChecker._set_rigctld_port(args, 9999)

    assert result == ["rigctld", "-m", "4", "-t", "9999"]


def test_set_rigctld_port_replaces_long_equals_port_option_at_end():
    args = ["rigctld", "-m", "4", "--port=4532"]

    result = RigChecker._set_rigctld_port(args, 9999)

    assert result == ["rigctld", "-m", "4", "-t", "9999"]


def test_set_rigctld_port_adds_port_if_missing():
    args = ["rigctld", "-m", "4", "-r", "127.0.0.1:12345"]

    result = RigChecker._set_rigctld_port(args, 9999)

    assert result == ["rigctld", "-m", "4", "-r", "127.0.0.1:12345", "-t", "9999"]


def test_set_rigctld_port_removes_multiple_existing_port_options():
    args = [
        "rigctld",
        "-t",
        "1111",
        "-m",
        "4",
        "--port=2222",
        "-r",
        "127.0.0.1:12345",
    ]

    result = RigChecker._set_rigctld_port(args, 9999)

    assert result == ["rigctld", "-m", "4", "-r", "127.0.0.1:12345", "-t", "9999"]


def test_set_rigctld_port_handles_dangling_short_port_option():
    args = ["rigctld", "-m", "4", "-t"]

    result = RigChecker._set_rigctld_port(args, 9999)

    assert result == ["rigctld", "-m", "4", "-t", "9999"]


def test_set_rigctld_port_handles_dangling_long_port_option():
    args = ["rigctld", "-m", "4", "--port"]

    result = RigChecker._set_rigctld_port(args, 9999)

    assert result == ["rigctld", "-m", "4", "-t", "9999"]