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
                "direct_timeout_seconds = 8\n",
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

    def test_switch_account_requires_existing_slot_auth(self):
        with TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            config = AppConfig(project_root=root, runtime_dir=root / ".runtime")

            with self.assertRaisesRegex(SwitchError, "does not have auth.json"):
                switch_account(config, "Missing", codex_home=root / "codex-home")

if __name__ == "__main__":
    unittest.main()
