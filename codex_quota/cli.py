from __future__ import annotations

import argparse
import os
import subprocess
import sys

from .accounts import account_slot_path
from .app import fetch_state
from .config import load_config
from .indicator import run_indicator
from .quota import (
    account_line,
    account_summary_line,
    indicator_label,
    last_updated_line,
    menu_window_line,
)
from .switcher import SwitchError, switch_account


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="codex-quota")
    subparsers = parser.add_subparsers(dest="command")
    subparsers.add_parser("run", help="run the AppIndicator")
    subparsers.add_parser("once", help="print one quota snapshot")
    subparsers.add_parser("doctor", help="check local dependencies")
    login_parser = subparsers.add_parser("login", help="login a standby account")
    login_parser.add_argument("alias", help="standby account alias, e.g. Work")
    switch_parser = subparsers.add_parser("switch", help="soft-switch current Codex account")
    switch_parser.add_argument("alias", help="standby account alias, e.g. Work")
    args = parser.parse_args(argv)

    command = args.command or "run"
    if command == "run":
        return run_indicator(load_config())
    if command == "once":
        return _once()
    if command == "doctor":
        return _doctor()
    if command == "login":
        return _login(args.alias)
    if command == "switch":
        return _switch(args.alias)
    parser.error(f"unknown command: {command}")
    return 2


def _once() -> int:
    config = load_config()
    state = fetch_state(config)
    snapshot = state.current
    print(account_line(snapshot))
    for window in snapshot.windows:
        print(menu_window_line(window))
    print(last_updated_line(snapshot))
    if state.standby:
        print()
        print("Accounts")
        print(account_summary_line(snapshot, current=True))
        for standby in state.standby:
            print(account_summary_line(standby))
    print(f"Top bar: {indicator_label(snapshot)}")
    return 1 if snapshot.error or any(item.error for item in state.standby) else 0


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


def _login(alias: str) -> int:
    config = load_config()
    try:
        codex_home = account_slot_path(config.accounts_dir, alias)
    except ValueError as exc:
        print(f"Invalid account alias: {exc}", file=sys.stderr)
        return 2
    codex_home.mkdir(parents=True, exist_ok=True)
    env = os.environ.copy()
    env["CODEX_HOME"] = str(codex_home)
    print(f"Logging in standby account '{codex_home.name}'")
    print(f"CODEX_HOME={codex_home}")
    return subprocess.call(["codex", "login"], env=env)


def _switch(alias: str) -> int:
    config = load_config()
    try:
        result = switch_account(config, alias)
    except (SwitchError, ValueError) as exc:
        print(f"Switch failed: {exc}", file=sys.stderr)
        return 1
    print(f"Switched to {result.alias}")
    print(f"Auth: {result.auth_path}")
    if result.backup_path:
        print(f"Backup: {result.backup_path}")
    if result.captured_current_path:
        print(f"Saved previous account slot: {result.captured_current_path}")
    print("New Codex processes will use this account.")
    print("Codex Desktop / running app-server may need restart.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
