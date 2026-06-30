from pathlib import Path
from tempfile import TemporaryDirectory
import threading
import time
import unittest
from unittest.mock import patch

from codex_quota.app import (
    _fetch_account_snapshot,
    _prune_temporary_codex_homes,
    fetch_state,
    load_cached_state,
)
from codex_quota.config import AppConfig
from codex_quota.quota import QuotaSnapshot, parse_rate_limits, save_cache


class AppStateTests(unittest.TestCase):
    def test_fetch_state_uses_selected_alias_as_current_account(self):
        with TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            accounts = root / ".runtime" / "accounts"
            for alias in ("Backup", "Personal", "Work"):
                slot = accounts / alias
                slot.mkdir(parents=True)
                (slot / "auth.json").write_text("{}")
            config = AppConfig(
                project_root=root,
                runtime_dir=root / ".runtime",
                selected_alias="Work",
            )

            with patch("codex_quota.app._fetch_slot_snapshot") as fetch:
                fetch.side_effect = lambda slot, runtime_dir=None: QuotaSnapshot(
                    alias=slot.alias,
                    email=None,
                    plan=None,
                    windows=[],
                    updated_at=0,
                )
                state = fetch_state(config)

            self.assertEqual(state.current.alias, "Work")
            self.assertEqual([snapshot.alias for snapshot in state.standby], ["Backup", "Personal"])

    def test_fetch_state_fetches_accounts_in_parallel(self):
        with TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            accounts = root / ".runtime" / "accounts"
            for alias in ("Backup", "Personal", "Work"):
                slot = accounts / alias
                slot.mkdir(parents=True)
                (slot / "auth.json").write_text("{}")
            config = AppConfig(
                project_root=root,
                runtime_dir=root / ".runtime",
                selected_alias="Work",
            )
            active = 0
            max_active = 0
            lock = threading.Lock()

            def slow_fetch(slot, runtime_dir=None):
                nonlocal active, max_active
                with lock:
                    active += 1
                    max_active = max(max_active, active)
                time.sleep(0.05)
                with lock:
                    active -= 1
                return QuotaSnapshot(
                    alias=slot.alias,
                    email=None,
                    plan=None,
                    windows=[],
                    updated_at=0,
                )

            with patch("codex_quota.app._fetch_slot_snapshot", side_effect=slow_fetch):
                state = fetch_state(config)

            self.assertEqual(state.current.alias, "Work")
            self.assertGreater(max_active, 1)

    def test_load_cached_state_uses_cache_without_live_fetch(self):
        with TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            accounts = root / ".runtime" / "accounts"
            for alias, used in (("Personal", 32), ("Work", 9)):
                slot = accounts / alias
                slot.mkdir(parents=True)
                (slot / "auth.json").write_text("{}")
                save_cache(
                    slot / "cache.json",
                    parse_rate_limits(
                        {
                            "rateLimits": {
                                "primary": {
                                    "usedPercent": used,
                                    "windowDurationMins": 300,
                                }
                            }
                        },
                        alias=alias,
                        email=f"{alias.lower()}@example.com",
                        now=100,
                    ),
                )
            config = AppConfig(
                project_root=root,
                runtime_dir=root / ".runtime",
                selected_alias="Work",
            )

            with patch("codex_quota.app._fetch_slot_snapshot") as live_fetch:
                state = load_cached_state(config)

            live_fetch.assert_not_called()
            self.assertEqual(state.current.alias, "Work")
            self.assertEqual(state.current.windows[0].left_percent, 91)
            self.assertEqual([snapshot.alias for snapshot in state.standby], ["Personal"])

    def test_fetch_account_snapshot_uses_short_app_server_timeout(self):
        with TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            auth_home = root / "auth"
            auth_home.mkdir()
            (auth_home / "auth.json").write_text("{}")
            client_instance = _FakeClient()

            with patch(
                "codex_quota.app.CodexAppServerClient",
                return_value=client_instance,
            ) as client:
                snapshot = _fetch_account_snapshot(
                    alias="Work",
                    auth_home=auth_home,
                    cache_path=auth_home / "cache.json",
                    runtime_dir=root / ".runtime",
                )

            self.assertEqual(snapshot.windows[0].left_percent, 68)
            self.assertEqual(client.call_args.kwargs["timeout_seconds"], 8.0)

    def test_fetch_account_snapshot_keeps_app_server_state_out_of_account_slot(self):
        with TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            slot = root / ".runtime" / "accounts" / "Work"
            slot.mkdir(parents=True)
            (slot / "auth.json").write_text("{}")

            with patch(
                "codex_quota.app.CodexAppServerClient",
                side_effect=lambda **kwargs: _PollutingFakeClient(**kwargs),
            ):
                snapshot = _fetch_account_snapshot(
                    alias="Work",
                    auth_home=slot,
                    cache_path=slot / "cache.json",
                    runtime_dir=root / ".runtime",
                )

            self.assertEqual(snapshot.windows[0].left_percent, 68)
            self.assertTrue((slot / "auth.json").exists())
            self.assertTrue((slot / "cache.json").exists())
            self.assertFalse((slot / ".tmp").exists())
            self.assertFalse((slot / "state_5.sqlite").exists())
            tmp_root = root / ".runtime" / "tmp" / "app-server"
            self.assertEqual(list(tmp_root.glob("codex-home-*")), [])

    def test_prune_temporary_codex_homes_removes_stale_auth_copies(self):
        with TemporaryDirectory() as tempdir:
            runtime = Path(tempdir) / ".runtime"
            stale = runtime / "tmp" / "app-server" / "codex-home-stale"
            stale.mkdir(parents=True)
            (stale / "auth.json").write_text("{}")
            (stale / "logs_2.sqlite").write_text("logs")

            _prune_temporary_codex_homes(runtime)

            self.assertFalse(stale.exists())


class _FakeClient:
    def read_rate_limits(self):
        return {
            "rateLimits": {
                "primary": {
                    "usedPercent": 32,
                    "windowDurationMins": 300,
                }
            }
        }


class _PollutingFakeClient:
    def __init__(self, *, codex_home, timeout_seconds):
        self.codex_home = codex_home
        self.timeout_seconds = timeout_seconds

    def read_rate_limits(self):
        plugins = self.codex_home / ".tmp" / "plugins"
        plugins.mkdir(parents=True)
        (plugins / "cache.txt").write_text("cache")
        (self.codex_home / "state_5.sqlite").write_text("state")
        return {
            "rateLimits": {
                "primary": {
                    "usedPercent": 32,
                    "windowDurationMins": 300,
                }
            }
        }


if __name__ == "__main__":
    unittest.main()
