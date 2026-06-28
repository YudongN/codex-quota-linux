from __future__ import annotations

import argparse
import sys

from .app import fetch_snapshot
from .config import load_config
from .indicator import run_indicator
from .quota import account_line, indicator_label, last_updated_line, menu_window_line


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="codex-quota")
    subparsers = parser.add_subparsers(dest="command")
    subparsers.add_parser("run", help="run the AppIndicator")
    subparsers.add_parser("once", help="print one quota snapshot")
    subparsers.add_parser("doctor", help="check local dependencies")
    args = parser.parse_args(argv)

    command = args.command or "run"
    if command == "run":
        return run_indicator(load_config())
    if command == "once":
        return _once()
    if command == "doctor":
        return _doctor()
    parser.error(f"unknown command: {command}")
    return 2


def _once() -> int:
    config = load_config()
    snapshot = fetch_snapshot(config)
    print(account_line(snapshot))
    for window in snapshot.windows:
        print(menu_window_line(window))
    print(last_updated_line(snapshot))
    print(f"Top bar: {indicator_label(snapshot)}")
    return 1 if snapshot.error else 0


def _doctor() -> int:
    ok = True
    try:
        import gi  # noqa: F401

        print("python-gi: ok")
    except Exception as exc:
        ok = False
        print(f"python-gi: missing ({exc})")
    try:
        import gi

        gi.require_version("Gtk", "3.0")
        from gi.repository import Gtk  # noqa: F401

        print("Gtk3: ok")
    except Exception as exc:
        ok = False
        print(f"Gtk3: missing ({exc})")
    try:
        import gi

        gi.require_version("AyatanaAppIndicator3", "0.1")
        from gi.repository import AyatanaAppIndicator3  # noqa: F401

        print("AyatanaAppIndicator3: ok")
    except Exception as exc:
        ok = False
        print(f"AyatanaAppIndicator3: missing ({exc})")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
