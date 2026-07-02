import inspect
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from codex_quota import indicator
from codex_quota.app import QuotaState
from codex_quota.config import AppConfig
from codex_quota.activation import ActivationResult
from codex_quota.indicator import (
    _activate_all_then_notify,
    _icon_for_status,
    _reorder_quota_for_alias,
    _run_background_action,
    _switch_then_notify,
)
from codex_quota.quota import QuotaSnapshot


class IndicatorTests(unittest.TestCase):
    def test_icon_names_follow_status_policy(self):
        self.assertEqual(_icon_for_status("ok"), "icon_green")
        self.assertEqual(_icon_for_status("warning"), "icon_yellow")
        self.assertEqual(_icon_for_status("danger"), "icon_red")
        self.assertEqual(_icon_for_status("stale"), "icon_gray")
        self.assertEqual(_icon_for_status("unknown"), "icon_gray")

    def test_switch_success_does_not_add_menu_message(self):
        source = inspect.getsource(indicator.run_indicator)

        self.assertNotIn("restart running Codex apps if needed", source)

    def test_indicator_startup_renders_cache_before_live_refresh(self):
        source = inspect.getsource(indicator.run_indicator)

        self.assertIn("apply_state(load_cached_state(config))", source)
        self.assertNotIn("apply_state(fetch_state(config))", source)

    def test_activate_all_menu_item_is_below_refresh_all(self):
        source = inspect.getsource(indicator.run_indicator)

        refresh_index = source.index('Gtk.MenuItem(label="Refresh all")')
        activate_index = source.index('Gtk.MenuItem(label="Activate all")')
        self.assertLess(refresh_index, activate_index)

    def test_standby_accounts_are_rendered_inside_switch_submenu(self):
        source = inspect.getsource(indicator._append_switch_account_submenu)

        self.assertIn('Gtk.MenuItem(label="Switch account")', source)
        self.assertIn("set_submenu", source)
        self.assertIn("standby_account_menu_lines", source)
        self.assertIn("_append_separator(switch_menu)", source)

    def test_minute_menu_text_timer_does_not_refresh_quota(self):
        source = inspect.getsource(indicator.run_indicator)
        timer_start = source.index("def menu_text_timer")
        timer_end = source.index("def open_config_folder")
        timer_source = source[timer_start:timer_end]

        self.assertIn("GLib.timeout_add_seconds(60, menu_text_timer)", source)
        self.assertIn("rebuild_menu(current_quota)", timer_source)
        self.assertNotIn("refresh_async()", timer_source)
        self.assertNotIn("fetch_state", timer_source)
        self.assertNotIn("fetch_snapshot", timer_source)
        self.assertNotIn("check_reset_credits", timer_source)

    def test_refresh_all_forces_reset_credits_refresh(self):
        source = inspect.getsource(indicator.run_indicator)

        self.assertIn("refresh_async(force_reset_credits=True)", source)
        self.assertIn(
            "fetch_state(current_config, refresh_reset_credits=True, force_reset_credits=force_reset_credits)",
            source,
        )

    def test_standby_timer_checks_reset_credits_ttl_without_force(self):
        source = inspect.getsource(indicator.run_indicator)
        timer_start = source.index("def standby_refresh_timer")
        timer_end = source.index("def menu_text_timer")
        timer_source = source[timer_start:timer_end]

        self.assertIn("refresh_standby_async()", timer_source)
        self.assertIn("refresh_async(force_reset_credits=False)", source)

    def test_account_sections_render_reset_credits_line(self):
        current_source = inspect.getsource(indicator._append_current_account_section)
        switch_source = inspect.getsource(indicator._append_switch_account_submenu)
        helper_source = inspect.getsource(indicator._account_lines_with_reset)

        self.assertIn("_account_lines_with_reset", current_source)
        self.assertIn("format_reset_credits_menu_line", helper_source)
        self.assertIn("reset_credits", switch_source)

    def test_indicator_workers_are_started_with_exception_guard(self):
        source = inspect.getsource(indicator.run_indicator)

        self.assertIn("_start_background_worker", source)
        self.assertNotIn("threading.Thread(target=worker", source)

    def test_background_action_routes_unexpected_exception_to_handler(self):
        errors: list[Exception] = []

        def worker() -> None:
            raise RuntimeError("boom")

        _run_background_action(worker, errors.append)

        self.assertEqual(len(errors), 1)
        self.assertIsInstance(errors[0], RuntimeError)
        self.assertEqual(str(errors[0]), "boom")

    def test_switch_then_notify_notifies_before_slow_refresh(self):
        calls: list[str] = []

        with TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            config = AppConfig(project_root=root, runtime_dir=root / ".runtime")

            def switch(config, alias):
                calls.append(f"switch:{alias}")

            def load():
                calls.append("load")
                return config

            def notify(alias):
                calls.append(f"notify:{alias}")

            _switch_then_notify(
                config,
                "Work",
                switch=switch,
                load=load,
                notify=notify,
            )
            calls.append("fetch_state")

        self.assertEqual(calls, ["switch:Work", "load", "notify:Work", "fetch_state"])

    def test_activate_all_then_notify_activates_all_accounts_before_notify(self):
        calls: list[str] = []
        results = [ActivationResult(alias="Work", status="success", tokens_used=8091)]

        with TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            config = AppConfig(project_root=root, runtime_dir=root / ".runtime")

            def activate(config, *, all_accounts, aliases):
                calls.append(f"activate:{all_accounts}:{aliases}")
                return results

            def notify(results):
                calls.append(f"notify:{results[0].alias}:{results[0].tokens_used}")

            actual = _activate_all_then_notify(
                config,
                activate=activate,
                notify=notify,
            )

        self.assertEqual(actual, results)
        self.assertEqual(calls, ["activate:True:[]", "notify:Work:8091"])

    def test_reorder_quota_for_alias_uses_cached_standby_before_refresh(self):
        personal = QuotaSnapshot(
            alias="Personal",
            email=None,
            plan=None,
            windows=[],
            updated_at=1,
        )
        work = QuotaSnapshot(
            alias="Work",
            email=None,
            plan=None,
            windows=[],
            updated_at=2,
        )
        backup = QuotaSnapshot(
            alias="Backup",
            email=None,
            plan=None,
            windows=[],
            updated_at=3,
        )

        reordered = _reorder_quota_for_alias(
            QuotaState(
                current=personal,
                standby=[backup, work],
                reset_credits={"Work": object()},
            ),
            "Work",
        )

        self.assertEqual(reordered.current.alias, "Work")
        self.assertEqual([snapshot.alias for snapshot in reordered.standby], ["Personal", "Backup"])
        self.assertIn("Work", reordered.reset_credits)


if __name__ == "__main__":
    unittest.main()
