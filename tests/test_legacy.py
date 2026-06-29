from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from codex_quota.legacy import migrate_legacy_homes


class LegacyMigrationTests(unittest.TestCase):
    def test_migrates_full_codex_home_files_but_keeps_auth_and_quota_cache(self):
        with TemporaryDirectory() as tempdir:
            runtime = Path(tempdir) / ".runtime"
            account = runtime / "accounts" / "Personal"
            account.mkdir(parents=True)
            (account / "auth.json").write_text("{}")
            (account / "cache.json").write_text("{}")
            (account / "state_5.sqlite").write_text("state")
            (account / "logs_2.sqlite").write_text("logs")
            (account / "plugins").mkdir()
            (account / "plugins" / "cache.txt").write_text("cache")

            report = migrate_legacy_homes(runtime, timestamp="20260629-120000")

            self.assertTrue((account / "auth.json").exists())
            self.assertTrue((account / "cache.json").exists())
            self.assertFalse((account / "state_5.sqlite").exists())
            archive = runtime / "legacy-codex-homes" / "20260629-120000" / "Personal"
            self.assertEqual((archive / "state_5.sqlite").read_text(), "state")
            self.assertEqual((archive / "logs_2.sqlite").read_text(), "logs")
            self.assertEqual((archive / "plugins" / "cache.txt").read_text(), "cache")
            self.assertEqual(report.migrated_accounts, ["Personal"])
            self.assertIn("Personal/state_5.sqlite", report.conversation_candidates)


if __name__ == "__main__":
    unittest.main()
