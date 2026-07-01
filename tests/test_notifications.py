import unittest
from unittest.mock import patch

from codex_quota.activation import ActivationResult
from codex_quota.notifications import notify_activation_results, notify_switch


class NotificationTests(unittest.TestCase):
    def test_notify_switch_uses_desktop_notification(self):
        with patch("subprocess.Popen") as popen:
            notify_switch("Work")

        popen.assert_called_once_with(
            [
                "notify-send",
                "[Codex Quota]",
                'Switched to Codex account "Work". Restart running Codex apps if needed.',
            ],
            stdout=-3,
            stderr=-3,
        )

    def test_notify_switch_ignores_missing_notify_send(self):
        with patch("subprocess.Popen", side_effect=OSError("missing")):
            notify_switch("Work")

    def test_notify_activation_results_summarizes_each_account(self):
        results = [
            ActivationResult(alias="XXX-A", status="success", tokens_used=8091),
            ActivationResult(alias="XXX-B", status="timeout"),
            ActivationResult(alias="XXX-C", status="failed"),
        ]

        with patch("subprocess.Popen") as popen:
            notify_activation_results(results)

        popen.assert_called_once_with(
            [
                "notify-send",
                "[Codex Quota]",
                'Account "XXX-A" activated successfully (tokens used: 8,091), '
                'Account "XXX-B" activation timeout, '
                'Account "XXX-C" activation failed',
            ],
            stdout=-3,
            stderr=-3,
        )


if __name__ == "__main__":
    unittest.main()
