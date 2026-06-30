from pathlib import Path
from tempfile import TemporaryDirectory
from datetime import datetime, timedelta
import unittest

from codex_quota.quota import (
    QuotaSchemaError,
    QuotaSnapshot,
    _format_reset,
    account_line,
    account_summary_line,
    current_account_menu_lines,
    failed_snapshot,
    freshness_line,
    header_action_line,
    indicator_label,
    last_updated_line,
    menu_limit_line,
    menu_meter_line,
    menu_window_line,
    parse_direct_usage,
    parse_rate_limits,
    progress_bar,
    save_cache,
    standby_account_menu_lines,
    status_name,
)


class QuotaParsingTests(unittest.TestCase):
    def test_parses_direct_usage_windows(self):
        snapshot = parse_direct_usage(
            {
                "plan_type": "plus",
                "rate_limit": {
                    "primary_window": {
                        "used_percent": 32,
                        "reset_at": 1782588600,
                        "limit_window_seconds": 18000,
                    },
                    "secondary_window": {
                        "used_percent": 57,
                        "reset_at": 1782975600,
                        "limit_window_seconds": 604800,
                    },
                },
                "credits": {},
            },
            alias="Main",
            email="user@example.com",
            now=100,
        )

        self.assertEqual(snapshot.plan, "plus")
        self.assertEqual(indicator_label(snapshot), "H68 · W43")
        self.assertEqual(snapshot.windows[0].label, "5h")
        self.assertEqual(snapshot.windows[0].reset_at, 1782588600)
        self.assertEqual(snapshot.windows[1].label, "7d")

    def test_direct_usage_missing_expected_fields_is_schema_drift(self):
        with self.assertRaisesRegex(QuotaSchemaError, "Backend changed"):
            parse_direct_usage(
                {"plan_type": "plus", "rate_limit": {}},
                alias="Main",
                email=None,
                now=100,
            )

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
        self.assertEqual(account_summary_line(snapshot, current=True), "● Main     H68 · W43")
        self.assertEqual(indicator_label(snapshot), "H68 · W43")
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

        self.assertEqual(indicator_label(snapshot), "M99")
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

    def test_status_prefers_5h_window_over_weekly_window(self):
        snapshot = parse_rate_limits(
            {
                "rateLimits": {
                    "primary": {
                        "usedPercent": 10,
                        "windowDurationMins": 300,
                    },
                    "secondary": {
                        "usedPercent": 95,
                        "windowDurationMins": 10080,
                    },
                }
            },
            alias="Main",
            email=None,
            now=100,
        )

        self.assertEqual(indicator_label(snapshot), "H90 · W5")
        self.assertEqual(status_name(snapshot), "ok")

    def test_progress_bar_is_twelve_cells(self):
        self.assertEqual(progress_bar(68), "████████░░░░")
        self.assertEqual(progress_bar(43), "█████░░░░░░░")

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
        self.assertEqual(menu_window_line(snapshot.windows[0]), "5h 68%")

    def test_menu_line_uses_relative_reset_for_same_day(self):
        now = datetime.now().astimezone().replace(
            hour=14, minute=8, second=0, microsecond=0
        )
        window = parse_rate_limits(
            {
                "rateLimits": {
                    "primary": {
                        "usedPercent": 32,
                        "windowDurationMins": 300,
                        "resetsAt": int((now + timedelta(hours=2, minutes=14)).timestamp()),
                    }
                }
            },
            alias="Personal",
            email=None,
            now=100,
        ).windows[0]

        self.assertEqual(
            menu_limit_line(window, now=now),
            "5h limit · reset in 2h 14m",
        )
        self.assertEqual(
            menu_meter_line(window),
            "████████░░░░  68%",
        )

    def test_menu_line_uses_short_day_count_for_monthly_reset(self):
        tz = datetime.now().astimezone().tzinfo
        now = datetime(2026, 6, 1, 14, 8, tzinfo=tz)
        window = parse_rate_limits(
            {
                "rateLimits": {
                    "planType": "free",
                    "individualLimit": {
                        "remainingPercent": 100,
                        "resetsAt": int(datetime(2026, 6, 29, 9, 0, tzinfo=tz).timestamp()),
                    },
                }
            },
            alias="Backup",
            email=None,
            now=100,
        ).windows[0]

        self.assertEqual(
            menu_window_line(window, now=now),
            "1mo 100% · reset Jun 29",
        )

    def test_menu_line_uses_weekday_time_for_non_today_reset(self):
        now = datetime.now().astimezone().replace(
            hour=14, minute=8, second=0, microsecond=0
        )
        reset = now + timedelta(days=3)
        reset = reset.replace(hour=9, minute=0)
        window = parse_rate_limits(
            {
                "rateLimits": {
                    "secondary": {
                        "usedPercent": 57,
                        "windowDurationMins": 10080,
                        "resetsAt": int(reset.timestamp()),
                    }
                }
            },
            alias="Personal",
            email=None,
            now=100,
        ).windows[0]

        self.assertEqual(
            menu_window_line(window, now=now),
            f"7d 43% · reset {reset.strftime('%a %H:%M')}",
        )

    def test_reset_text_follows_menu_time_rules(self):
        tz = datetime.now().astimezone().tzinfo
        now = datetime(2026, 6, 29, 14, 8, tzinfo=tz)

        def line_for(delta: timedelta) -> str:
            window = parse_rate_limits(
                {
                    "rateLimits": {
                        "primary": {
                            "usedPercent": 32,
                            "windowDurationMins": 300,
                            "resetsAt": int((now + delta).timestamp()),
                        }
                    }
                },
                alias="Personal",
                email=None,
                now=100,
            ).windows[0]
            return menu_limit_line(window, now=now)

        self.assertEqual(line_for(timedelta(seconds=30)), "5h limit · reset now")
        self.assertEqual(line_for(timedelta(minutes=42)), "5h limit · reset in 42m")
        self.assertEqual(line_for(timedelta(hours=2, minutes=14)), "5h limit · reset in 2h 14m")
        self.assertEqual(line_for(timedelta(hours=7, minutes=22)), "5h limit · reset today 21:30")
        self.assertEqual(line_for(timedelta(hours=18)), "5h limit · reset tomorrow 08:08")
        self.assertEqual(line_for(timedelta(days=4, hours=3, minutes=22)), "5h limit · reset Fri 17:30")

        same_year = parse_rate_limits(
            {
                "rateLimits": {
                    "primary": {
                        "usedPercent": 32,
                        "windowDurationMins": 300,
                        "resetsAt": int(datetime(2026, 7, 8, 9, 0, tzinfo=tz).timestamp()),
                    }
                }
            },
            alias="Personal",
            email=None,
            now=100,
        ).windows[0]
        next_year = parse_rate_limits(
            {
                "rateLimits": {
                    "primary": {
                        "usedPercent": 32,
                        "windowDurationMins": 300,
                        "resetsAt": int(datetime(2027, 1, 3, 9, 0, tzinfo=tz).timestamp()),
                    }
                }
            },
            alias="Personal",
            email=None,
            now=100,
        ).windows[0]

        self.assertEqual(menu_limit_line(same_year, now=now), "5h limit · reset Jul 8")
        self.assertEqual(menu_limit_line(next_year, now=now), "5h limit · reset Jan 3, 2027")

    def test_header_action_line_adds_switch_action(self):
        snapshot = parse_rate_limits(
            {
                "rateLimits": {
                    "planType": "team",
                    "primary": {
                        "usedPercent": 9,
                        "windowDurationMins": 300,
                    },
                }
            },
            alias="Work",
            email="work@example.com",
            now=100,
        )

        self.assertEqual(header_action_line(snapshot, "Switch"), "Work · Team                 Switch")

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
        self.assertEqual(indicator_label(stale), "H68 · W43")
        expected_time = datetime.fromtimestamp(100).astimezone().strftime("%H:%M:%S")
        self.assertEqual(last_updated_line(stale, now=120), f"Updated at {expected_time}")
        self.assertEqual(status_name(stale, now=120), "warning")
        self.assertEqual(status_name(stale, now=701), "warning")
        self.assertEqual(status_name(stale, now=3700), "stale")
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
        self.assertEqual(last_updated_line(snapshot), "Updated at never")

    def test_freshness_line_uses_short_relative_states(self):
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
            now=1_000,
        )

        self.assertEqual(freshness_line(snapshot, now=1_020), "Updated right now")
        self.assertEqual(freshness_line(snapshot, now=1_120), "Updated 2m ago")
        self.assertEqual(freshness_line(snapshot, now=4_540), "Updated 59m ago")
        self.assertEqual(freshness_line(snapshot, now=4_600), "Stale")

    def test_freshness_line_maps_actionable_errors_to_short_labels(self):
        cached = QuotaSnapshot(
            alias="Work",
            email="work@example.com",
            plan="plus",
            windows=[],
            updated_at=1_000,
            error="direct quota auth failed",
        )
        changed = QuotaSnapshot(
            alias="Work",
            email="work@example.com",
            plan="plus",
            windows=[],
            updated_at=1_000,
            error="Backend changed",
        )

        self.assertEqual(freshness_line(cached, now=1_020), "Auth needed")
        self.assertEqual(freshness_line(changed, now=1_020), "Backend changed")

    def test_freshness_line_does_not_treat_initial_cache_miss_as_auth_needed(self):
        snapshot = QuotaSnapshot(
            alias="Work",
            email=None,
            plan=None,
            windows=[],
            updated_at=0,
            error="not refreshed yet",
        )

        self.assertEqual(freshness_line(snapshot, now=1_020), "Stale")

    def test_freshness_line_hides_transient_error_when_cache_exists(self):
        cached = QuotaSnapshot(
            alias="Work",
            email="work@example.com",
            plan="plus",
            windows=[
                parse_rate_limits(
                    {
                        "rateLimits": {
                            "primary": {
                                "usedPercent": 32,
                                "windowDurationMins": 300,
                            }
                        }
                    },
                    alias="Work",
                    email="work@example.com",
                    now=1_000,
                ).windows[0]
            ],
            updated_at=1_000,
            error="quota request failed",
        )

        text = freshness_line(cached, now=1_120)

        self.assertEqual(text, "Updated 2m ago")
        self.assertNotIn("Network issue", text)
        self.assertNotIn("quota request failed", text)

    def test_current_account_menu_lines_use_compact_window_style(self):
        now = datetime.now().astimezone().replace(
            hour=14, minute=8, second=0, microsecond=0
        )
        snapshot = parse_rate_limits(
            {
                "rateLimits": {
                    "planType": "plus",
                    "primary": {
                        "usedPercent": 100,
                        "windowDurationMins": 300,
                        "resetsAt": int((now + timedelta(hours=4, minutes=15)).timestamp()),
                    },
                }
            },
            alias="Outlook",
            email="outlook@example.com",
            now=int(now.timestamp()),
        )

        lines = current_account_menu_lines(
            snapshot,
            now=now,
            freshness_now=int(now.timestamp()) + 20,
        )

        self.assertEqual(lines[0], "✓ Outlook · Plus")
        self.assertEqual(lines[1], "outlook@example.com")
        self.assertIn("5h 0% · reset in 4h 15m", lines)
        self.assertIn("Updated right now", lines)
        self.assertFalse(any("limit" in line for line in lines))
        self.assertFalse(any("█" in line or "░" in line for line in lines))

    def test_standby_account_menu_lines_start_with_switch_action(self):
        snapshot = parse_rate_limits(
            {
                "rateLimits": {
                    "planType": "plus",
                    "primary": {
                        "usedPercent": 35,
                        "windowDurationMins": 300,
                    },
                }
            },
            alias="Gmail",
            email=None,
            now=1_000,
        )

        lines = standby_account_menu_lines(snapshot, freshness_now=1_120)

        self.assertEqual(lines[0], "Switch to Gmail · Plus")
        self.assertIn("5h 65%", lines)
        self.assertIn("Updated 2m ago", lines)


if __name__ == "__main__":
    unittest.main()
