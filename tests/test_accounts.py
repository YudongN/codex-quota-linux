import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from codex_quota.accounts import account_slot_path, discover_account_slots


class AccountSlotTests(unittest.TestCase):
    def test_discovers_auth_json_slots_sorted_by_alias(self):
        with TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            (root / "Work").mkdir()
            (root / "Work" / "auth.json").write_text("{}")
            (root / "Backup").mkdir()
            (root / "Backup" / "auth.json").write_text("{}")
            (root / "NotAnAccount").mkdir()
            (root / "notes.txt").write_text("ignore")

            slots = discover_account_slots(root)

        self.assertEqual([slot.alias for slot in slots], ["Backup", "Work"])

    def test_account_slot_path_rejects_path_like_aliases(self):
        root = Path("/tmp/accounts")

        self.assertEqual(account_slot_path(root, "Work"), root / "Work")
        for alias in ("", ".", "..", "../Work", "Team/Work", "Team\\Work"):
            with self.subTest(alias=alias):
                with self.assertRaises(ValueError):
                    account_slot_path(root, alias)


if __name__ == "__main__":
    unittest.main()
