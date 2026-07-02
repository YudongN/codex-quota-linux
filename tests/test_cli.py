import contextlib
import io
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from codex_quota import cli
from codex_quota.activation import ActivationResult
from codex_quota.config import AppConfig
from codex_quota.reset_credits import ResetCredit, ResetCreditsSnapshot


class CliTests(unittest.TestCase):
    def test_migrate_legacy_homes_is_not_a_supported_command(self):
        stderr = io.StringIO()

        with contextlib.redirect_stderr(stderr):
            with self.assertRaises(SystemExit) as raised:
                cli.main(["migrate-legacy-homes"])

        self.assertEqual(raised.exception.code, 2)
        self.assertIn("invalid choice", stderr.getvalue())

    def test_activate_window_cli_forwards_selection_and_timeout(self):
        with TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            config = AppConfig(project_root=root, runtime_dir=root / ".runtime")

            with patch("codex_quota.cli.load_config", return_value=config), patch(
                "codex_quota.cli.activate_window",
                return_value=[
                    ActivationResult(alias="Work", status="success", tokens_used=8091)
                ],
            ) as activate:
                stdout = io.StringIO()
                with contextlib.redirect_stdout(stdout):
                    result = cli.main(
                        [
                            "activate-window",
                            "--alias",
                            "Work",
                            "--timeout",
                            "7",
                        ]
                    )

        self.assertEqual(result, 0)
        activate.assert_called_once()
        self.assertEqual(activate.call_args.kwargs["aliases"], ["Work"])
        self.assertFalse(activate.call_args.kwargs["all_accounts"])
        self.assertFalse(activate.call_args.kwargs["dry_run"])
        self.assertEqual(activate.call_args.kwargs["timeout_seconds"], 7)
        self.assertIn("Work: success (tokens used: 8,091)", stdout.getvalue())

    def test_check_reset_credits_cli_forwards_selection(self):
        with TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            config = AppConfig(project_root=root, runtime_dir=root / ".runtime")
            snapshots = [
                ResetCreditsSnapshot(
                    alias="Work",
                    available_count=1,
                    credits=[
                        ResetCredit(
                            status="available",
                            title="Later",
                            granted_at="2026-06-01T00:00:00Z",
                            expires_at="2026-07-20T00:00:00Z",
                        )
                    ],
                    updated_at=100,
                ),
                ResetCreditsSnapshot(
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
                ),
            ]

            with patch("codex_quota.cli.load_config", return_value=config), patch(
                "codex_quota.cli.check_reset_credits",
                return_value=snapshots,
            ) as check:
                stdout = io.StringIO()
                with contextlib.redirect_stdout(stdout):
                    result = cli.main(["check-reset-credits", "--all"])

        self.assertEqual(result, 0)
        check.assert_called_once()
        self.assertTrue(check.call_args.kwargs["all_accounts"])
        self.assertEqual(check.call_args.kwargs["aliases"], [])
        output = stdout.getvalue()
        self.assertLess(output.index("Backup"), output.index("Work"))
        self.assertIn("available_count", output)
        self.assertIn("expires_at", output)


if __name__ == "__main__":
    unittest.main()
