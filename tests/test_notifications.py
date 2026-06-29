import unittest
from unittest.mock import patch

from codex_quota.notifications import notify_switch


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


if __name__ == "__main__":
    unittest.main()
