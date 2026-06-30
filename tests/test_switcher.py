import json
import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from codex_quota.config import AppConfig
from codex_quota.switcher import SwitchError, switch_account


class SwitcherTests(unittest.TestCase):
    def test_switch_account_replaces_auth_without_persistent_backup(self):
        with TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            runtime = root / ".runtime"
            codex_home = root / "codex-home"
            codex_home.mkdir()
            (codex_home / "auth.json").write_text('{"account":"main"}')
            os.chmod(codex_home / "auth.json", 0o600)
            work_home = runtime / "accounts" / "Work"
            work_home.mkdir(parents=True)
            (work_home / "auth.json").write_text('{"account":"work"}')
            config = AppConfig(
                project_root=root,
                runtime_dir=runtime,
                selected_alias="Main",
                active_refresh_interval_seconds=120,
                standby_refresh_interval_seconds=600,
            )

            result = switch_account(config, "Work", codex_home=codex_home)

            self.assertEqual((codex_home / "auth.json").read_text(), '{"account":"work"}')
            self.assertEqual(oct((codex_home / "auth.json").stat().st_mode & 0o777), "0o600")
            self.assertFalse((runtime / "backups").exists())
            self.assertFalse((runtime / "accounts" / "Main" / "auth.json").exists())
            self.assertEqual(
                (runtime / "config.toml").read_text(),
                'selected_alias = "Work"\n'
                "active_refresh_interval_seconds = 120\n"
                "standby_refresh_interval_seconds = 600\n"
                "direct_max_attempts = 3\n"
                "direct_timeout_seconds = 8\n"
                "activate_timeout_seconds = 90\n",
            )

    def test_switch_account_without_existing_auth_has_no_backup(self):
        with TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            runtime = root / ".runtime"
            codex_home = root / "codex-home"
            work_home = runtime / "accounts" / "Work"
            work_home.mkdir(parents=True)
            (work_home / "auth.json").write_text('{"account":"work"}')
            config = AppConfig(project_root=root, runtime_dir=runtime)

            result = switch_account(config, "Work", codex_home=codex_home)

            self.assertEqual((codex_home / "auth.json").read_text(), '{"account":"work"}')
            self.assertFalse((runtime / "backups").exists())

    def test_switch_account_syncs_selected_slot_before_replacement(self):
        with TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            runtime = root / ".runtime"
            codex_home = root / "codex-home"
            main_home = runtime / "accounts" / "Main"
            work_home = runtime / "accounts" / "Work"
            codex_home.mkdir()
            main_home.mkdir(parents=True)
            work_home.mkdir(parents=True)
            _write_auth(
                main_home / "auth.json",
                account_id="acct-main",
                marker="slot-original",
            )
            _write_auth(
                codex_home / "auth.json",
                account_id="acct-main",
                marker="main-refreshed",
            )
            _write_auth(work_home / "auth.json", account_id="acct-work", marker="work")
            config = AppConfig(
                project_root=root,
                runtime_dir=runtime,
                selected_alias="Main",
            )

            switch_account(config, "Work", codex_home=codex_home)

            self.assertEqual(_auth_marker(main_home / "auth.json"), "main-refreshed")
            self.assertEqual(_auth_mode(main_home / "auth.json"), "0o600")
            self.assertEqual(_auth_marker(codex_home / "auth.json"), "work")

    def test_switch_account_does_not_sync_mismatched_selected_slot(self):
        with TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            runtime = root / ".runtime"
            codex_home = root / "codex-home"
            main_home = runtime / "accounts" / "Main"
            work_home = runtime / "accounts" / "Work"
            codex_home.mkdir()
            main_home.mkdir(parents=True)
            work_home.mkdir(parents=True)
            _write_auth(
                main_home / "auth.json",
                account_id="acct-main",
                marker="slot-original",
            )
            _write_auth(
                codex_home / "auth.json",
                account_id="acct-other",
                marker="main-refreshed",
            )
            _write_auth(work_home / "auth.json", account_id="acct-work", marker="work")
            config = AppConfig(
                project_root=root,
                runtime_dir=runtime,
                selected_alias="Main",
            )

            switch_account(config, "Work", codex_home=codex_home)

            self.assertEqual(_auth_marker(main_home / "auth.json"), "slot-original")
            self.assertEqual(_auth_marker(codex_home / "auth.json"), "work")

    def test_switch_account_requires_existing_slot_auth(self):
        with TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            config = AppConfig(project_root=root, runtime_dir=root / ".runtime")

            with self.assertRaisesRegex(SwitchError, "does not have auth.json"):
                switch_account(config, "Missing", codex_home=root / "codex-home")


def _write_auth(path, *, account_id, marker):
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
