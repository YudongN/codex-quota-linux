import unittest
import inspect

from codex_quota import indicator
from codex_quota.indicator import _icon_for_status


class IndicatorTests(unittest.TestCase):
    def test_icon_names_follow_status_policy(self):
        self.assertEqual(_icon_for_status("ok"), "icon_green")
        self.assertEqual(_icon_for_status("warning"), "icon_yellow")
        self.assertEqual(_icon_for_status("danger"), "icon_red")
        self.assertEqual(_icon_for_status("stale"), "icon_gray")
        self.assertEqual(_icon_for_status("unknown"), "icon_gray")

    def test_switch_success_does_not_add_menu_message(self):
        source = inspect.getsource(indicator.run_indicator)

        self.assertNotIn("restart running Codex apps if needed", source)


if __name__ == "__main__":
    unittest.main()
