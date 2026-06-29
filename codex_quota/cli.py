from __future__ import annotations

import argparse
import sys

from .app import fetch_state
from .auth_store import AddAccountError, add_account
from .config import load_config
from .indicator import run_indicator
from .legacy import migrate_legacy_homes
from .notifications import notify_switch
from .quota import (
    header_action_line,
    header_line,
    indicator_label,
    last_updated_line,
    menu_limit_line,
    menu_meter_line,
    menu_window_line,
)
from .switcher import SwitchError, switch_account


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="codex-quota")
    subparsers = parser.add_subparsers(dest="command")
    subparsers.add_parser("run", help="run the AppIndicator")
    subparsers.add_parser("once", help="print one quota snapshot")
    subparsers.add_parser("doctor", help="check local dependencies")
    add_parser = subparsers.add_parser("add", help="add an account by alias")
    add_parser.add_argument("alias", help="account alias, e.g. Personal")
    switch_parser = subparsers.add_parser("switch", help="soft-switch current Codex account")
    switch_parser.add_argument("alias", help="account alias, e.g. Work")
    subparsers.add_parser(
        "migrate-legacy-homes",
        help="archive old full CODEX_HOME files under .runtime/accounts",
    )
    args = parser.parse_args(argv)

    command = args.command or "run"
    if command == "run":
        return run_indicator(load_config())
    if command == "once":
        return _once()
    if command == "doctor":
        return _doctor()
    if command == "add":
        return _add(args.alias)
    if command == "switch":
        return _switch(args.alias)
    if command == "migrate-legacy-homes":
        return _migrate_legacy_homes()
    parser.error(f"unknown command: {command}")
    return 2


def _once() -> int:
    config = load_config()
    state = fetch_state(config)
    snapshot = state.current
    _print_snapshot(snapshot)
    if state.standby:
        for standby in state.standby:
            print("─────────────────────────────")
            _print_standby_snapshot(standby)
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


def _add(alias: str) -> int:
    config = load_config()
    try:
        result = add_account(config, alias)
    except (AddAccountError, ValueError) as exc:
        print(f"Add account failed: {exc}", file=sys.stderr)
        return 1
    print(f"Added account {result.alias}")
    print(f"Stored auth: {result.auth_path}")
    print("Restored original ~/.codex/auth.json")
    return 0


def _switch(alias: str) -> int:
    config = load_config()
    try:
        result = switch_account(config, alias)
    except (SwitchError, ValueError) as exc:
        print(f"Switch failed: {exc}", file=sys.stderr)
        return 1
    print(f"Switched to {result.alias}")
    print(f"Auth: {result.auth_path}")
    notify_switch(result.alias)
    print("New Codex processes will use this account.")
    print("Codex Desktop / running app-server may need restart.")
    return 0


def _migrate_legacy_homes() -> int:
    config = load_config()
    report = migrate_legacy_homes(config.runtime_dir)
    if not report.migrated_accounts:
        print("No legacy CODEX_HOME files found.")
        return 0
    print(f"Archived legacy files: {report.archive_root}")
    for alias in report.migrated_accounts:
        print(f"- {alias}")
    if report.conversation_candidates:
        print("Conversation-state candidates were archived, not merged:")
        for item in report.conversation_candidates:
            print(f"- {item}")
    return 0


def _print_snapshot(snapshot) -> None:
    print(header_line(snapshot))
    print(snapshot.email or "Unknown account")
    for window in snapshot.windows:
        print(menu_limit_line(window))
        print(menu_meter_line(window))
    if not snapshot.windows:
        print("Quota unavailable")
    print(last_updated_line(snapshot))


def _print_standby_snapshot(snapshot) -> None:
    print(header_action_line(snapshot, "Switch"))
    for window in snapshot.windows:
        print(menu_window_line(window))
    if not snapshot.windows:
        print("Quota unavailable")


if __name__ == "__main__":
    sys.exit(main())
