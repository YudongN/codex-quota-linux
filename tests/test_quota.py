from pathlib import Path
from tempfile import TemporaryDirectory
from datetime import datetime, timedelta
import unittest

from codex_quota.quota import (
    _format_reset,
    account_line,
    failed_snapshot,
    indicator_label,
    last_updated_line,
    menu_window_line,
    parse_rate_limits,
    progress_bar,
    save_cache,
    status_name,
)


class QuotaParsingTests(unittest.TestCase):
    def test_parses_codex_primary_and_secondary_as_left_percent(self):
        snapshot = parse_rate_limits(
            {
                "rateLimitsByLimitId": {
                    "codex": {
                        "planType": "plus",
                        "primary": {
                            "usedPercent": 32,
                            "windowDurationMins": 300,
                            "resetsAt": 1782588600,
                        },
                        "secondary": {
                            "usedPercent": 57,
                            "windowDurationMins": 10080,
                            "resetsAt": 1782975600,
                        },
                    }
                },
                "rateLimits": {},
            },
            alias="Main",
            email="user@example.com",
            now=100,
        )

        self.assertEqual(snapshot.plan, "plus")
        self.assertEqual(account_line(snapshot), "Main: user@example.com (Plus)")
        self.assertEqual(indicator_label(snapshot), "H68% · W43%")
        self.assertEqual(status_name(snapshot), "warning")
        self.assertEqual(snapshot.windows[0].label, "5h")
        self.assertEqual(snapshot.windows[1].label, "7d")

    def test_parses_individual_limit_as_monthly_fallback(self):
        snapshot = parse_rate_limits(
            {
                "rateLimits": {
                    "planType": "free",
                    "individualLimit": {
                        "remainingPercent": 99,
                        "resetsAt": 1782975600,
                        "limit": "100",
                        "used": "1",
                    },
                }
            },
            alias="Backup",
            email=None,
            now=100,
        )

        self.assertEqual(indicator_label(snapshot), "M99%")
        self.assertEqual(status_name(snapshot), "ok")

    def test_status_thresholds_follow_icon_policy(self):
        def snapshot_for_left(left_percent: int):
            return parse_rate_limits(
                {
                    "rateLimits": {
                        "primary": {
                            "usedPercent": 100 - left_percent,
                            "windowDurationMins": 300,
                        }
                    }
                },
                alias="Main",
                email=None,
                now=100,
            )

        self.assertEqual(status_name(snapshot_for_left(71)), "ok")
        self.assertEqual(status_name(snapshot_for_left(70)), "warning")
        self.assertEqual(status_name(snapshot_for_left(30)), "warning")
        self.assertEqual(status_name(snapshot_for_left(29)), "danger")

    def test_progress_bar_is_ten_cells(self):
        self.assertEqual(progress_bar(68), "███████░░░")
        self.assertEqual(progress_bar(43), "████░░░░░░")

    def test_menu_line_contains_label_percent_and_left_text(self):
        snapshot = parse_rate_limits(
            {
                "rateLimits": {
                    "primary": {
                        "usedPercent": 32,
                        "windowDurationMins": 300,
                    }
                }
            },
            alias="Main",
            email=None,
            now=100,
        )

        self.assertIn("5h", menu_window_line(snapshot.windows[0]))
        self.assertEqual(menu_window_line(snapshot.windows[0]), "5h: 68% left")

    def test_reset_format_uses_time_today_and_date_otherwise(self):
        now = datetime.now().astimezone().replace(
            hour=12, minute=0, second=0, microsecond=0
        )
        later_today = now.replace(hour=21, minute=30)
        later_week = now + timedelta(days=6)

        self.assertEqual(
            _format_reset(int(later_today.timestamp()), now=now),
            "21:30",
        )
        self.assertEqual(
            _format_reset(int(later_week.timestamp()), now=now),
            later_week.strftime("%-d %b"),
        )

    def test_failed_snapshot_uses_cached_quota_as_stale_data(self):
        cached = parse_rate_limits(
            {
                "rateLimits": {
                    "primary": {
                        "usedPercent": 32,
                        "windowDurationMins": 300,
                    },
                    "secondary": {
                        "usedPercent": 57,
                        "windowDurationMins": 10080,
                    },
                }
            },
            alias="Main",
            email="user@example.com",
            now=100,
        )

        with TemporaryDirectory() as tempdir:
            cache_path = Path(tempdir) / "cache.json"
            save_cache(cache_path, cached)
            stale = failed_snapshot(
                alias="Main",
                email=None,
                error="usage endpoint failed",
                cache_path=cache_path,
            )

        self.assertTrue(stale.is_stale)
        self.assertEqual(stale.email, "user@example.com")
        self.assertEqual(indicator_label(stale), "H68% · W43%")
        expected_time = datetime.fromtimestamp(100).astimezone().strftime("%H:%M:%S")
        self.assertEqual(last_updated_line(stale, now=120), f"Last updated: {expected_time}")
        self.assertEqual(status_name(stale, now=120), "warning")
        self.assertEqual(status_name(stale, now=701), "stale")
        self.assertIn(
            "stale: usage endpoint failed",
            last_updated_line(stale, now=120, include_error=True),
        )

    def test_failed_snapshot_without_cache_has_no_last_successful_update(self):
        snapshot = failed_snapshot(
            alias="Main",
            email=None,
            error="usage endpoint failed",
            cache_path=None,
        )

        self.assertEqual(status_name(snapshot), "unknown")
        self.assertEqual(last_updated_line(snapshot), "Last updated: never")


if __name__ == "__main__":
    unittest.main()
