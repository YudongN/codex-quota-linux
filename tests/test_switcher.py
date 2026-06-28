import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from codex_quota.config import AppConfig
from codex_quota.switcher import SwitchError, switch_account


class SwitcherTests(unittest.TestCase):
    def test_switch_account_replaces_auth_backs_up_and_updates_config(self):
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
                current_alias="Main",
                refresh_interval_seconds=120,
            )

            result = switch_account(config, "Work", codex_home=codex_home)

            self.assertEqual((codex_home / "auth.json").read_text(), '{"account":"work"}')
            self.assertEqual(oct((codex_home / "auth.json").stat().st_mode & 0o777), "0o600")
            self.assertIsNotNone(result.backup_path)
            assert result.backup_path is not None
            self.assertEqual(result.backup_path.read_text(), '{"account":"main"}')
            self.assertEqual(oct(result.backup_path.stat().st_mode & 0o777), "0o600")
            captured = runtime / "accounts" / "Main" / "auth.json"
            self.assertEqual(captured.read_text(), '{"account":"main"}')
            self.assertEqual(oct(captured.stat().st_mode & 0o777), "0o600")
            self.assertEqual(
                (runtime / "config.toml").read_text(),
                'current_alias = "Work"\nrefresh_interval_seconds = 120\n',
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
            self.assertIsNone(result.backup_path)
            self.assertIsNone(result.captured_current_path)

    def test_switch_account_requires_existing_slot_auth(self):
        with TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            config = AppConfig(project_root=root, runtime_dir=root / ".runtime")

            with self.assertRaisesRegex(SwitchError, "does not have auth.json"):
                switch_account(config, "Missing", codex_home=root / "codex-home")

if __name__ == "__main__":
    unittest.main()
