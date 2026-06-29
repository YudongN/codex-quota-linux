from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from codex_quota.app import fetch_state
from codex_quota.config import AppConfig
from codex_quota.quota import QuotaSnapshot


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


if __name__ == "__main__":
    unittest.main()
