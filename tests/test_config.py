from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from codex_quota.config import AppConfig, load_config, save_config


class ConfigTests(unittest.TestCase):
    def test_load_config_creates_runtime_defaults(self):
        with TemporaryDirectory() as tempdir:
            root = Path(tempdir)

            config = load_config(root=root)

            self.assertEqual(config.selected_alias, "")
            self.assertEqual(config.active_refresh_interval_seconds, 120)
            self.assertEqual(config.standby_refresh_interval_seconds, 600)
            self.assertEqual(
                (root / ".runtime" / "config.toml").read_text(),
                'selected_alias = ""\n'
                "active_refresh_interval_seconds = 120\n"
                "standby_refresh_interval_seconds = 600\n",
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
            self.assertEqual(
                (runtime / "config.toml").read_text(),
                'selected_alias = "Outlook"\n'
                "active_refresh_interval_seconds = 120\n"
                "standby_refresh_interval_seconds = 600\n",
            )

    def test_save_config_writes_only_current_keys(self):
        with TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            config = AppConfig(
                project_root=root,
                runtime_dir=root / ".runtime",
                selected_alias="Personal",
                active_refresh_interval_seconds=120,
                standby_refresh_interval_seconds=600,
            )

            save_config(config, selected_alias="Work")

            self.assertEqual(
                (root / ".runtime" / "config.toml").read_text(),
                'selected_alias = "Work"\n'
                "active_refresh_interval_seconds = 120\n"
                "standby_refresh_interval_seconds = 600\n",
            )


if __name__ == "__main__":
    unittest.main()
