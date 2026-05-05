import sys

from pansyncer.main import PanSyncer


def test_parse_args_small_display_default_is_none(monkeypatch):
    monkeypatch.setattr(sys, "argv", ["pansyncer"])

    args = PanSyncer.parse_args()

    assert args.small_display is None