from __future__ import annotations

from collections.abc import Callable
import subprocess
import threading

from .activation import ActivationError, activate_window
from .app import QuotaState, fetch_snapshot, fetch_state, load_cached_state
from .config import AppConfig, load_config
from .notifications import notify_activation_results, notify_switch
from .quota import (
    current_account_menu_lines,
    indicator_label,
    standby_account_menu_lines,
    status_name,
)
from .reset_credits import format_reset_credits_menu_line
from .switcher import SwitchError, switch_account


def run_indicator(config: AppConfig) -> int:
    import gi

    gi.require_version("Gtk", "3.0")
    gi.require_version("AyatanaAppIndicator3", "0.1")
    from gi.repository import AyatanaAppIndicator3 as AppIndicator3
    from gi.repository import GLib, Gtk

    state: dict[str, object] = {
        "config": config,
        "quota": None,
        "message": None,
    }

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
        _append_current_account_section(
            menu,
            snapshot,
            quota.reset_credits.get(snapshot.alias),
        )
        _append_separator(menu)
        _append_switch_account_submenu(
            menu,
            quota.standby,
            quota.reset_credits,
            on_switch=switch_async,
        )
        message = state.get("message")
        if isinstance(message, str) and message:
            _append_separator(menu)
            _append_label(menu, message)
        _append_separator(menu)
        refresh_item = Gtk.MenuItem(label="Refresh all")
        refresh_item.connect("activate", lambda _item: refresh_async(force_reset_credits=True))
        menu.append(refresh_item)
        activate_item = Gtk.MenuItem(label="Activate all")
        activate_item.connect("activate", lambda _item: activate_all_async())
        menu.append(activate_item)
        open_item = Gtk.MenuItem(label="Open config folder...")
        open_item.connect("activate", lambda _item: open_config_folder())
        menu.append(open_item)
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

    def apply_worker_error(message: str) -> None:
        state["message"] = message
        current_quota = state.get("quota")
        if isinstance(current_quota, QuotaState):
            rebuild_menu(current_quota)

    def worker_error(prefix: str) -> Callable[[Exception], None]:
        return lambda exc: GLib.idle_add(apply_worker_error, f"{prefix} failed: {exc}")

    def refresh_async(
        *,
        refresh_reset_credits: bool = True,
        force_reset_credits: bool = False,
    ) -> None:
        def worker() -> None:
            current_config = state["config"]
            assert isinstance(current_config, AppConfig)
            if refresh_reset_credits:
                quota = fetch_state(current_config, refresh_reset_credits=True, force_reset_credits=force_reset_credits)
            else:
                quota = fetch_state(current_config)
            GLib.idle_add(apply_state, quota)

        _start_background_worker(worker, worker_error("Refresh"))

    def refresh_active_async() -> None:
        def worker() -> None:
            current_config = state["config"]
            assert isinstance(current_config, AppConfig)
            current = fetch_snapshot(current_config)
            quota = state.get("quota")
            if isinstance(quota, QuotaState):
                next_quota = QuotaState(
                    current=current,
                    standby=quota.standby,
                    reset_credits=quota.reset_credits,
                )
            else:
                next_quota = fetch_state(current_config)
            GLib.idle_add(apply_state, next_quota)

        _start_background_worker(worker, worker_error("Refresh"))

    def refresh_standby_async() -> None:
        refresh_async(force_reset_credits=False)

    def switch_async(alias: str) -> None:
        def apply_switch_selected(new_config: AppConfig, alias: str) -> None:
            state["config"] = new_config
            state["message"] = None
            current_quota = state.get("quota")
            if isinstance(current_quota, QuotaState):
                apply_state(_reorder_quota_for_alias(current_quota, alias))

        def apply_switch_success(quota: QuotaState) -> None:
            apply_state(quota)

        def apply_switch_error(message: str) -> None:
            state["message"] = message
            current_quota = state.get("quota")
            if isinstance(current_quota, QuotaState):
                rebuild_menu(current_quota)

        def worker() -> None:
            current_config = state["config"]
            assert isinstance(current_config, AppConfig)
            try:
                new_config = _switch_then_notify(current_config, alias)
                GLib.idle_add(apply_switch_selected, new_config, alias)
                quota = fetch_state(new_config)
                GLib.idle_add(apply_switch_success, quota)
            except (SwitchError, ValueError) as exc:
                GLib.idle_add(apply_switch_error, f"Switch failed: {exc}")

        _start_background_worker(worker, worker_error("Switch"))

    def activate_all_async() -> None:
        def apply_activate_success(quota: QuotaState) -> None:
            state["message"] = None
            apply_state(quota)

        def apply_activate_error(message: str) -> None:
            state["message"] = message
            current_quota = state.get("quota")
            if isinstance(current_quota, QuotaState):
                rebuild_menu(current_quota)

        def worker() -> None:
            current_config = state["config"]
            assert isinstance(current_config, AppConfig)
            try:
                _activate_all_then_notify(current_config)
                quota = fetch_state(current_config)
                GLib.idle_add(apply_activate_success, quota)
            except (ActivationError, ValueError) as exc:
                GLib.idle_add(apply_activate_error, f"Activate all failed: {exc}")

        _start_background_worker(worker, worker_error("Activate all"))

    def active_refresh_timer() -> bool:
        refresh_active_async()
        return True

    def standby_refresh_timer() -> bool:
        refresh_standby_async()
        return True

    def menu_text_timer() -> bool:
        current_quota = state.get("quota")
        if isinstance(current_quota, QuotaState):
            rebuild_menu(current_quota)
        return True

    def open_config_folder() -> None:
        current_config = state["config"]
        assert isinstance(current_config, AppConfig)
        current_config.runtime_dir.mkdir(parents=True, exist_ok=True)
        try:
            subprocess.Popen(
                ["xdg-open", str(current_config.runtime_dir)],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except OSError as exc:
            state["message"] = f"Open config folder failed: {exc}"
            current_quota = state.get("quota")
            if isinstance(current_quota, QuotaState):
                rebuild_menu(current_quota)

    apply_state(load_cached_state(config))
    refresh_async(force_reset_credits=True)
    GLib.timeout_add_seconds(60, menu_text_timer)
    GLib.timeout_add_seconds(
        config.quota_active_refresh_interval_seconds,
        active_refresh_timer,
    )
    GLib.timeout_add_seconds(
        config.quota_standby_refresh_interval_seconds,
        standby_refresh_timer,
    )
    Gtk.main()
    return 0


def _switch_then_notify(
    config: AppConfig,
    alias: str,
    *,
    switch=switch_account,
    load=load_config,
    notify=notify_switch,
) -> AppConfig:
    switch(config, alias)
    new_config = load()
    notify(alias)
    return new_config


def _activate_all_then_notify(
    config: AppConfig,
    *,
    activate=activate_window,
    notify=notify_activation_results,
):
    results = activate(config, all_accounts=True, aliases=[])
    notify(results)
    return results


def _start_background_worker(
    worker: Callable[[], None],
    on_error: Callable[[Exception], None],
) -> None:
    threading.Thread(
        target=lambda: _run_background_action(worker, on_error),
        daemon=True,
    ).start()


def _run_background_action(
    worker: Callable[[], None],
    on_error: Callable[[Exception], None],
) -> None:
    try:
        worker()
    except Exception as exc:
        on_error(exc)


def _reorder_quota_for_alias(quota: QuotaState, alias: str) -> QuotaState:
    if quota.current.alias == alias:
        return quota
    for index, snapshot in enumerate(quota.standby):
        if snapshot.alias != alias:
            continue
        standby = [quota.current]
        standby.extend(quota.standby[:index])
        standby.extend(quota.standby[index + 1 :])
        return QuotaState(
            current=snapshot,
            standby=standby,
            reset_credits=quota.reset_credits,
        )
    return quota


def _append_current_account_section(menu, snapshot, reset_credits=None) -> None:
    for line in _account_lines_with_reset(
        current_account_menu_lines(snapshot),
        reset_credits,
    ):
        _append_label(menu, line)


def _append_switch_account_submenu(menu, snapshots, reset_credits, on_switch) -> None:
    import gi

    gi.require_version("Gtk", "3.0")
    from gi.repository import Gtk

    item = Gtk.MenuItem(label="Switch account")
    if not snapshots:
        item.set_sensitive(False)
        menu.append(item)
        return
    switch_menu = Gtk.Menu()
    for index, snapshot in enumerate(snapshots):
        if index:
            _append_separator(switch_menu)
        lines = _account_lines_with_reset(
            standby_account_menu_lines(snapshot),
            reset_credits.get(snapshot.alias),
        )
        action_item = Gtk.MenuItem(label=lines[0])
        action_item.connect(
            "activate",
            lambda _item, alias=snapshot.alias: on_switch(alias),
        )
        switch_menu.append(action_item)
        for line in lines[1:]:
            _append_label(switch_menu, line)
    item.set_submenu(switch_menu)
    menu.append(item)


def _account_lines_with_reset(lines: list[str], reset_credits) -> list[str]:
    next_lines = list(lines)
    insert_at = max(0, len(next_lines) - 1)
    next_lines.insert(insert_at, format_reset_credits_menu_line(reset_credits))
    return next_lines


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
