import unittest

from codex_quota.indicator import _icon_for_status


class IndicatorTests(unittest.TestCase):
    def test_icon_names_follow_status_policy(self):
        self.assertEqual(_icon_for_status("ok"), "icon_green")
        self.assertEqual(_icon_for_status("warning"), "icon_yellow")
        self.assertEqual(_icon_for_status("danger"), "icon_red")
        self.assertEqual(_icon_for_status("stale"), "icon_gray")
        self.assertEqual(_icon_for_status("unknown"), "icon_gray")


if __name__ == "__main__":
    unittest.main()
