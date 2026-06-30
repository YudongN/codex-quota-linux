import json
import os
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
from codex_quota.client import (
    CodexClientError,
    DirectQuotaAuthError,
    DirectQuotaTransientError,
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

    def test_fetch_account_snapshot_uses_direct_quota_before_app_server(self):
        with TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            auth_home = root / "auth"
            auth_home.mkdir()
            (auth_home / "auth.json").write_text("{}")
            direct_instance = _FakeDirectClient()

            with patch(
                "codex_quota.app.DirectQuotaClient",
                return_value=direct_instance,
            ) as direct_client, patch("codex_quota.app.CodexAppServerClient") as app_client:
                snapshot = _fetch_account_snapshot(
                    alias="Work",
                    auth_home=auth_home,
                    cache_path=auth_home / "cache.json",
                    runtime_dir=root / ".runtime",
                    direct_max_attempts=3,
                    direct_timeout_seconds=8,
                )

            self.assertEqual(snapshot.windows[0].left_percent, 68)
            self.assertEqual(snapshot.plan, "plus")
            self.assertEqual(direct_instance.auth_home, auth_home)
            self.assertEqual(direct_client.call_args.kwargs["max_attempts"], 3)
            self.assertEqual(direct_client.call_args.kwargs["timeout_seconds"], 8)
            app_client.assert_not_called()

    def test_fetch_account_snapshot_auth_failure_repairs_with_app_server(self):
        with TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            auth_home = root / "auth"
            auth_home.mkdir()
            (auth_home / "auth.json").write_text("{}")
            client_instance = _FakeClient()

            with patch(
                "codex_quota.app.DirectQuotaClient",
                return_value=_FailingDirectClient(
                    DirectQuotaAuthError("direct quota auth failed")
                ),
            ), patch(
                "codex_quota.app.CodexAppServerClient",
                return_value=client_instance,
            ) as client:
                snapshot = _fetch_account_snapshot(
                    alias="Work",
                    auth_home=auth_home,
                    cache_path=auth_home / "cache.json",
                    runtime_dir=root / ".runtime",
                    direct_max_attempts=3,
                    direct_timeout_seconds=8,
                )

            self.assertEqual(snapshot.windows[0].left_percent, 68)
            self.assertIsNone(snapshot.error)
            self.assertEqual(client.call_args.kwargs["timeout_seconds"], 8.0)

    def test_fetch_account_snapshot_copies_back_refreshed_app_server_auth(self):
        with TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            auth_home = root / ".runtime" / "accounts" / "Work"
            auth_home.mkdir(parents=True)
            auth_path = auth_home / "auth.json"
            _write_auth(auth_path, account_id="acct-work", marker="original")

            with patch(
                "codex_quota.app.DirectQuotaClient",
                return_value=_FailingDirectClient(
                    DirectQuotaAuthError("direct quota auth failed")
                ),
            ), patch(
                "codex_quota.app.CodexAppServerClient",
                side_effect=lambda **kwargs: _RefreshingFakeClient(
                    marker="refreshed",
                    **kwargs,
                ),
            ):
                snapshot = _fetch_account_snapshot(
                    alias="Work",
                    auth_home=auth_home,
                    cache_path=auth_home / "cache.json",
                    runtime_dir=root / ".runtime",
                    direct_max_attempts=3,
                    direct_timeout_seconds=8,
                )

            self.assertEqual(snapshot.windows[0].left_percent, 68)
            self.assertEqual(_auth_marker(auth_path), "refreshed")
            self.assertEqual(_auth_mode(auth_path), "0o600")

    def test_fetch_account_snapshot_does_not_copy_back_mismatched_auth(self):
        with TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            auth_home = root / ".runtime" / "accounts" / "Work"
            auth_home.mkdir(parents=True)
            auth_path = auth_home / "auth.json"
            _write_auth(auth_path, account_id="acct-work", marker="original")

            with patch(
                "codex_quota.app.DirectQuotaClient",
                return_value=_FailingDirectClient(
                    DirectQuotaAuthError("direct quota auth failed")
                ),
            ), patch(
                "codex_quota.app.CodexAppServerClient",
                side_effect=lambda **kwargs: _RefreshingFakeClient(
                    account_id="acct-other",
                    marker="refreshed",
                    **kwargs,
                ),
            ):
                snapshot = _fetch_account_snapshot(
                    alias="Work",
                    auth_home=auth_home,
                    cache_path=auth_home / "cache.json",
                    runtime_dir=root / ".runtime",
                    direct_max_attempts=3,
                    direct_timeout_seconds=8,
                )

            self.assertEqual(snapshot.windows[0].left_percent, 68)
            self.assertEqual(_auth_marker(auth_path), "original")

    def test_fetch_account_snapshot_does_not_copy_back_failed_app_server_auth(self):
        with TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            auth_home = root / ".runtime" / "accounts" / "Work"
            auth_home.mkdir(parents=True)
            auth_path = auth_home / "auth.json"
            _write_auth(auth_path, account_id="acct-work", marker="original")

            with patch(
                "codex_quota.app.DirectQuotaClient",
                return_value=_FailingDirectClient(
                    DirectQuotaAuthError("direct quota auth failed")
                ),
            ), patch(
                "codex_quota.app.CodexAppServerClient",
                side_effect=lambda **kwargs: _FailingRefreshingFakeClient(**kwargs),
            ):
                snapshot = _fetch_account_snapshot(
                    alias="Work",
                    auth_home=auth_home,
                    cache_path=auth_home / "cache.json",
                    runtime_dir=root / ".runtime",
                    direct_max_attempts=3,
                    direct_timeout_seconds=8,
                )

            self.assertTrue(snapshot.is_stale)
            self.assertEqual(_auth_marker(auth_path), "original")

    def test_fetch_account_snapshot_schema_drift_repairs_with_app_server(self):
        with TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            auth_home = root / "auth"
            auth_home.mkdir()
            (auth_home / "auth.json").write_text("{}")

            with patch(
                "codex_quota.app.DirectQuotaClient",
                return_value=_DirectPayloadClient({"rate_limit": {}}),
            ), patch(
                "codex_quota.app.CodexAppServerClient",
                return_value=_FakeClient(used_percent=9),
            ) as client:
                snapshot = _fetch_account_snapshot(
                    alias="Work",
                    auth_home=auth_home,
                    cache_path=auth_home / "cache.json",
                    runtime_dir=root / ".runtime",
                    direct_max_attempts=3,
                    direct_timeout_seconds=8,
                )

            self.assertEqual(snapshot.windows[0].left_percent, 91)
            self.assertIsNone(snapshot.error)
            client.assert_called_once()

    def test_fetch_account_snapshot_transient_direct_failure_uses_cache_only(self):
        with TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            auth_home = root / "auth"
            auth_home.mkdir()
            (auth_home / "auth.json").write_text("{}")
            cache_path = auth_home / "cache.json"
            save_cache(
                cache_path,
                parse_rate_limits(
                    {
                        "rateLimits": {
                            "primary": {
                                "usedPercent": 20,
                                "windowDurationMins": 300,
                            }
                        }
                    },
                    alias="Work",
                    email="work@example.com",
                    now=100,
                ),
            )

            with patch(
                "codex_quota.app.DirectQuotaClient",
                return_value=_FailingDirectClient(
                    DirectQuotaTransientError("quota request failed")
                ),
            ), patch("codex_quota.app.CodexAppServerClient") as app_client:
                snapshot = _fetch_account_snapshot(
                    alias="Work",
                    auth_home=auth_home,
                    cache_path=cache_path,
                    runtime_dir=root / ".runtime",
                    direct_max_attempts=3,
                    direct_timeout_seconds=8,
                )

            self.assertTrue(snapshot.is_stale)
            self.assertEqual(snapshot.windows[0].left_percent, 80)
            self.assertEqual(snapshot.error, "quota request failed")
            app_client.assert_not_called()

    def test_fetch_account_snapshot_keeps_app_server_state_out_of_account_slot(self):
        with TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            slot = root / ".runtime" / "accounts" / "Work"
            slot.mkdir(parents=True)
            (slot / "auth.json").write_text("{}")

            with patch(
                "codex_quota.app.DirectQuotaClient",
                return_value=_FailingDirectClient(
                    DirectQuotaAuthError("direct quota auth failed")
                ),
            ), patch(
                "codex_quota.app.CodexAppServerClient",
                side_effect=lambda **kwargs: _PollutingFakeClient(**kwargs),
            ):
                snapshot = _fetch_account_snapshot(
                    alias="Work",
                    auth_home=slot,
                    cache_path=slot / "cache.json",
                    runtime_dir=root / ".runtime",
                    direct_max_attempts=3,
                    direct_timeout_seconds=8,
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
    def __init__(self, used_percent=32):
        self.used_percent = used_percent

    def read_rate_limits(self):
        return {
            "rateLimits": {
                "primary": {
                    "usedPercent": self.used_percent,
                    "windowDurationMins": 300,
                }
            }
        }


class _FakeDirectClient:
    def __init__(self):
        self.auth_home = None

    def read_usage(self, auth_home):
        self.auth_home = auth_home
        return _direct_usage(32)


class _DirectPayloadClient:
    def __init__(self, payload):
        self.payload = payload

    def read_usage(self, _auth_home):
        return self.payload


class _FailingDirectClient:
    def __init__(self, error):
        self.error = error

    def read_usage(self, _auth_home):
        raise self.error


def _direct_usage(used_percent):
    return {
        "plan_type": "plus",
        "rate_limit": {
            "primary_window": {
                "used_percent": used_percent,
                "limit_window_seconds": 18000,
            }
        },
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


class _RefreshingFakeClient:
    def __init__(
        self,
        *,
        codex_home,
        timeout_seconds,
        account_id="acct-work",
        marker="refreshed",
    ):
        self.codex_home = codex_home
        self.timeout_seconds = timeout_seconds
        self.account_id = account_id
        self.marker = marker

    def read_rate_limits(self):
        _write_auth(
            self.codex_home / "auth.json",
            account_id=self.account_id,
            marker=self.marker,
        )
        return {
            "rateLimits": {
                "primary": {
                    "usedPercent": 32,
                    "windowDurationMins": 300,
                }
            }
        }


class _FailingRefreshingFakeClient:
    def __init__(self, *, codex_home, timeout_seconds):
        self.codex_home = codex_home
        self.timeout_seconds = timeout_seconds

    def read_rate_limits(self):
        _write_auth(
            self.codex_home / "auth.json",
            account_id="acct-work",
            marker="refreshed",
        )
        raise CodexClientError("app-server failed")


def _write_auth(path, *, account_id, marker):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "marker": marker,
                "tokens": {
                    "account_id": account_id,
                    "access_token": "dummy-access",
                    "refresh_token": "dummy-refresh",
                },
            },
            sort_keys=True,
        )
    )
    os.chmod(path, 0o600)


def _auth_marker(path):
    return json.loads(path.read_text())["marker"]


def _auth_mode(path):
    return oct(path.stat().st_mode & 0o777)


if __name__ == "__main__":
    unittest.main()
