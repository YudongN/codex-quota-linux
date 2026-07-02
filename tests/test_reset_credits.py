from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from codex_quota.reset_credits import (
    ResetCredit,
    ResetCreditsSchemaError,
    ResetCreditsSnapshot,
    format_reset_credits_menu_line,
    load_reset_credits_cache,
    parse_reset_credits,
    reset_credits_cache_is_fresh,
    reset_credits_table_rows,
    save_reset_credits_cache,
)


class ResetCreditsTests(unittest.TestCase):
    def test_parse_reset_credits_extracts_safe_fields(self):
        snapshot = parse_reset_credits(
            {
                "available_count": 2,
                "credits": [
                    {
                        "status": "available",
                        "title": "Reset 1",
                        "granted_at": "2026-06-01T00:00:00Z",
                        "expires_at": "2026-07-01T00:00:00Z",
                        "account_id": "do-not-store",
                    },
                    {
                        "status": "available",
                        "title": "Reset 2",
                        "granted_at": "2026-06-03T00:00:00Z",
                        "expires_at": "2026-06-20T00:00:00Z",
                    },
                ],
            },
            alias="Work",
            now=100,
        )

        self.assertEqual(snapshot.alias, "Work")
        self.assertEqual(snapshot.available_count, 2)
        self.assertEqual(snapshot.updated_at, 100)
        self.assertEqual(snapshot.credits[0].expires_at, "2026-07-01T00:00:00Z")
        self.assertFalse(hasattr(snapshot.credits[0], "account_id"))

    def test_parse_reset_credits_rejects_schema_drift(self):
        with self.assertRaisesRegex(ResetCreditsSchemaError, "Backend changed"):
            parse_reset_credits({"credits": []}, alias="Work", now=100)

    def test_cache_round_trip_uses_json(self):
        with TemporaryDirectory() as tempdir:
            path = Path(tempdir) / "reset_credits_cache.json"
            snapshot = ResetCreditsSnapshot(
                alias="Work",
                available_count=1,
                credits=[
                    ResetCredit(
                        status="available",
                        title="Reset",
                        granted_at="2026-06-01T00:00:00Z",
                        expires_at="2026-07-01T00:00:00Z",
                    )
                ],
                updated_at=100,
            )

            save_reset_credits_cache(path, snapshot)
            loaded = load_reset_credits_cache(path)

        self.assertEqual(loaded, snapshot)

    def test_cache_freshness_uses_configured_ttl(self):
        snapshot = ResetCreditsSnapshot(
            alias="Work",
            available_count=0,
            credits=[],
            updated_at=100,
        )

        self.assertTrue(
            reset_credits_cache_is_fresh(snapshot, now=199, ttl_seconds=100)
        )
        self.assertFalse(
            reset_credits_cache_is_fresh(snapshot, now=200, ttl_seconds=100)
        )

    def test_table_rows_sort_by_expiry_across_accounts(self):
        work = ResetCreditsSnapshot(
            alias="Work",
            available_count=1,
            credits=[
                ResetCredit(
                    status="available",
                    title="Later",
                    granted_at="2026-06-01T00:00:00Z",
                    expires_at="2026-07-10T00:00:00Z",
                )
            ],
            updated_at=100,
        )
        backup = ResetCreditsSnapshot(
            alias="Backup",
            available_count=1,
            credits=[
                ResetCredit(
                    status="available",
                    title="Sooner",
                    granted_at="2026-06-01T00:00:00Z",
                    expires_at="2026-07-01T00:00:00Z",
                )
            ],
            updated_at=100,
        )

        rows = reset_credits_table_rows([work, backup])

        self.assertEqual([row["alias"] for row in rows], ["Backup", "Work"])
        self.assertEqual(rows[0]["available_count"], "1")
        self.assertEqual(rows[0]["status"], "available")

    def test_menu_line_shows_next_expiry_relative_days(self):
        snapshot = ResetCreditsSnapshot(
            alias="Work",
            available_count=4,
            credits=[
                ResetCredit(
                    status="available",
                    title="Reset",
                    granted_at="2026-06-01T00:00:00Z",
                    expires_at="2026-07-28T00:00:00Z",
                )
            ],
            updated_at=100,
        )

        line = format_reset_credits_menu_line(snapshot, now=1782777600)

        self.assertEqual(line, "Resets 4 · expires in 28d")

    def test_menu_line_uses_short_error_states(self):
        snapshot = ResetCreditsSnapshot(
            alias="Work",
            available_count=4,
            credits=[],
            updated_at=100,
            error="direct reset credits auth failed",
        )

        self.assertEqual(format_reset_credits_menu_line(snapshot), "Resets Auth needed")


if __name__ == "__main__":
    unittest.main()
