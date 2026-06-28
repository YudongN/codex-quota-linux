from __future__ import annotations

import threading

from .app import QuotaState, fetch_state
from .config import AppConfig
from .quota import (
    account_line,
    account_summary_line,
    indicator_label,
    last_updated_line,
    menu_window_line,
    status_name,
)


def run_indicator(config: AppConfig) -> int:
    import gi

    gi.require_version("Gtk", "3.0")
    gi.require_version("AyatanaAppIndicator3", "0.1")
    from gi.repository import AyatanaAppIndicator3 as AppIndicator3
    from gi.repository import GLib, Gtk

    state: dict[str, QuotaState | None] = {"quota": None}

    indicator = AppIndicator3.Indicator.new(
        "codex-quota-linux",
        "icon_gray",
        AppIndicator3.IndicatorCategory.APPLICATION_STATUS,
    )
    indicator.set_icon_theme_path(str(config.project_root / "assets"))
    indicator.set_status(AppIndicator3.IndicatorStatus.ACTIVE)

    def rebuild_menu(quota: QuotaState) -> None:
        snapshot = quota.current
        menu = Gtk.Menu()
        _append_label(menu, account_line(snapshot))
        if snapshot.windows:
            for window in snapshot.windows:
                _append_label(menu, menu_window_line(window))
        else:
            _append_label(menu, "Quota unavailable")
        _append_label(menu, last_updated_line(snapshot))
        if quota.standby:
            _append_separator(menu)
            _append_label(menu, "Accounts")
            _append_label(menu, account_summary_line(snapshot, current=True))
            for standby in quota.standby:
                _append_label(menu, account_summary_line(standby))
        _append_separator(menu)
        refresh_item = Gtk.MenuItem(label="Refresh all")
        refresh_item.connect("activate", lambda _item: refresh_async())
        menu.append(refresh_item)
        quit_item = Gtk.MenuItem(label="Quit")
        quit_item.connect("activate", lambda _item: Gtk.main_quit())
        menu.append(quit_item)
        menu.show_all()
        indicator.set_menu(menu)

    def apply_state(quota: QuotaState) -> None:
        snapshot = quota.current
        state["quota"] = quota
        indicator.set_label(indicator_label(snapshot), "")
        indicator.set_icon_full(_icon_for_status(status_name(snapshot)), "Codex quota")
        rebuild_menu(quota)

    def refresh_async() -> None:
        def worker() -> None:
            quota = fetch_state(config)
            GLib.idle_add(apply_state, quota)

        threading.Thread(target=worker, daemon=True).start()

    def refresh_timer() -> bool:
        refresh_async()
        return True

    apply_state(fetch_state(config))
    GLib.timeout_add_seconds(config.refresh_interval_seconds, refresh_timer)
    Gtk.main()
    return 0


def _append_label(menu, text: str):
    import gi

    gi.require_version("Gtk", "3.0")
    from gi.repository import Gtk

    item = Gtk.MenuItem(label=text)
    item.set_sensitive(False)
    menu.append(item)
    return item


def _append_separator(menu) -> None:
    import gi

    gi.require_version("Gtk", "3.0")
    from gi.repository import Gtk

    menu.append(Gtk.SeparatorMenuItem())


def _icon_for_status(status: str) -> str:
    if status == "ok":
        return "icon_green"
    if status == "warning":
        return "icon_yellow"
    if status == "danger":
        return "icon_red"
    return "icon_gray"
