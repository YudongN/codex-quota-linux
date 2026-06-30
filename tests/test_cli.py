import contextlib
import io
import unittest

from codex_quota import cli


class CliTests(unittest.TestCase):
    def test_migrate_legacy_homes_is_not_a_supported_command(self):
        stderr = io.StringIO()

        with contextlib.redirect_stderr(stderr):
            with self.assertRaises(SystemExit) as raised:
                cli.main(["migrate-legacy-homes"])

        self.assertEqual(raised.exception.code, 2)
        self.assertIn("invalid choice", stderr.getvalue())


if __name__ == "__main__":
    unittest.main()
