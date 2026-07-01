from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from codex_quota.config import AppConfig, load_config, save_config


class ConfigTests(unittest.TestCase):
    def test_load_config_creates_runtime_defaults(self):
        with TemporaryDirectory() as tempdir:
            root = Path(tempdir)

            config = load_config(root=root)

            self.assertEqual(config.selected_alias, "")
            self.assertEqual(config.active_refresh_interval_seconds, 120)
            self.assertEqual(config.standby_refresh_interval_seconds, 600)
            self.assertEqual(config.direct_max_attempts, 3)
            self.assertEqual(config.direct_timeout_seconds, 8)
            self.assertEqual(config.activate_timeout_seconds, 90)
            self.assertEqual(
                (root / ".runtime" / "config.toml").read_text(),
                'selected_alias = ""\n'
                "active_refresh_interval_seconds = 120\n"
                "standby_refresh_interval_seconds = 600\n"
                "direct_max_attempts = 3\n"
                "direct_timeout_seconds = 8\n"
                "activate_timeout_seconds = 90\n",
            )

    def test_load_config_migrates_old_current_alias_without_main_default(self):
        with TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            runtime = root / ".runtime"
            runtime.mkdir()
            (runtime / "config.toml").write_text(
                'current_alias = "Outlook"\nrefresh_interval_seconds = 60\n'
            )

            config = load_config(root=root)

            self.assertEqual(config.selected_alias, "Outlook")
            self.assertEqual(config.active_refresh_interval_seconds, 120)
            self.assertEqual(config.standby_refresh_interval_seconds, 600)
            self.assertEqual(config.direct_max_attempts, 3)
            self.assertEqual(config.direct_timeout_seconds, 8)
            self.assertEqual(config.activate_timeout_seconds, 90)
            self.assertEqual(
                (runtime / "config.toml").read_text(),
                'selected_alias = "Outlook"\n'
                "active_refresh_interval_seconds = 120\n"
                "standby_refresh_interval_seconds = 600\n"
                "direct_max_attempts = 3\n"
                "direct_timeout_seconds = 8\n"
                "activate_timeout_seconds = 90\n",
            )

    def test_load_config_does_not_rewrite_complete_current_config(self):
        with TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            runtime = root / ".runtime"
            runtime.mkdir()
            (runtime / "config.toml").write_text(
                'selected_alias = "Work"\n'
                "active_refresh_interval_seconds = 180\n"
                "standby_refresh_interval_seconds = 900\n"
                "direct_max_attempts = 4\n"
                "direct_timeout_seconds = 9\n"
                "activate_timeout_seconds = 12\n"
            )

            with patch("codex_quota.config.save_config") as save:
                config = load_config(root=root)

            save.assert_not_called()
            self.assertEqual(config.selected_alias, "Work")
            self.assertEqual(config.active_refresh_interval_seconds, 180)
            self.assertEqual(config.standby_refresh_interval_seconds, 900)
            self.assertEqual(config.direct_max_attempts, 4)
            self.assertEqual(config.direct_timeout_seconds, 9)
            self.assertEqual(config.activate_timeout_seconds, 12)

    def test_save_config_writes_only_current_keys(self):
        with TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            config = AppConfig(
                project_root=root,
                runtime_dir=root / ".runtime",
                selected_alias="Personal",
                active_refresh_interval_seconds=120,
                standby_refresh_interval_seconds=600,
                direct_max_attempts=4,
                direct_timeout_seconds=9,
                activate_timeout_seconds=12,
            )

            save_config(config, selected_alias="Work")

            self.assertEqual(
                (root / ".runtime" / "config.toml").read_text(),
                'selected_alias = "Work"\n'
                "active_refresh_interval_seconds = 120\n"
                "standby_refresh_interval_seconds = 600\n"
                "direct_max_attempts = 4\n"
                "direct_timeout_seconds = 9\n"
                "activate_timeout_seconds = 12\n",
            )

    def test_save_config_ignores_preexisting_fixed_temp_symlink(self):
        with TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            runtime = root / ".runtime"
            runtime.mkdir()
            outside = root / "outside.txt"
            outside.write_text("do not touch")
            (runtime / ".config.toml.tmp").symlink_to(outside)
            config = AppConfig(project_root=root, runtime_dir=runtime)

            save_config(config, selected_alias="Work")

            self.assertEqual(outside.read_text(), "do not touch")
            self.assertFalse((runtime / "config.toml").is_symlink())
            self.assertIn('selected_alias = "Work"', (runtime / "config.toml").read_text())


if __name__ == "__main__":
    unittest.main()
