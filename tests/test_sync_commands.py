from pansyncer.sync import SyncManager


def test_build_normal_frequency_set_command():
    assert SyncManager._build_cat_cmd(14_074_000) == b"F 14074000\n"


def test_build_lnb_lo_set_command():
    assert SyncManager._build_cat_cmd(73_095_000, is_lo=True) == b"LNB_LO 73095000\n"


def test_build_command_accepts_negative_lo_value():
    assert SyncManager._build_cat_cmd(-58_895_000, is_lo=True) == b"LNB_LO -58895000\n"