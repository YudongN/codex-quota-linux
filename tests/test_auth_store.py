import os
from pathlib import Path
from tempfile import TemporaryDirectory
import textwrap
import unittest

from codex_quota.auth_store import AddAccountError, add_account
from codex_quota.config import AppConfig


class AuthStoreTests(unittest.TestCase):
    def test_add_account_imports_login_auth_and_restores_previous_default_auth(self):
        with TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            runtime = root / ".runtime"
            codex_home = root / "codex-home"
            codex_home.mkdir()
            auth_path = codex_home / "auth.json"
            auth_path.write_text('{"account":"old"}')
            os.chmod(auth_path, 0o600)
            login_script = _write_login_script(
                root,
                """
                import pathlib
                import sys

                auth_path = pathlib.Path(sys.argv[1]) / "auth.json"
                auth_path.write_text('{"account":"new"}')
                """
            )
            config = AppConfig(project_root=root, runtime_dir=runtime)

            result = add_account(
                config,
                "Personal",
                codex_home=codex_home,
                login_command=["python3", str(login_script), str(codex_home)],
            )

            self.assertEqual(auth_path.read_text(), '{"account":"old"}')
            stored_auth = runtime / "accounts" / "Personal" / "auth.json"
            self.assertEqual(stored_auth.read_text(), '{"account":"new"}')
            self.assertEqual(oct(stored_auth.stat().st_mode & 0o777), "0o600")
            self.assertEqual(result.alias, "Personal")
            self.assertEqual(result.auth_path, stored_auth)
            self.assertFalse((runtime / "backups").exists())
            self.assertEqual(
                (runtime / "config.toml").read_text(),
                'selected_alias = "Personal"\n'
                "active_refresh_interval_seconds = 120\n"
                "standby_refresh_interval_seconds = 600\n"
                "direct_max_attempts = 3\n"
                "direct_timeout_seconds = 8\n"
                "activate_timeout_seconds = 90\n",
            )

    def test_add_account_restores_missing_default_auth_to_missing_state(self):
        with TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            runtime = root / ".runtime"
            codex_home = root / "codex-home"
            codex_home.mkdir()
            login_script = _write_login_script(
                root,
                """
                import pathlib
                import sys

                auth_path = pathlib.Path(sys.argv[1]) / "auth.json"
                auth_path.write_text('{"account":"new"}')
                """
            )
            config = AppConfig(project_root=root, runtime_dir=runtime)

            add_account(
                config,
                "Personal",
                codex_home=codex_home,
                login_command=["python3", str(login_script), str(codex_home)],
            )

            self.assertFalse((codex_home / "auth.json").exists())
            self.assertEqual(
                (runtime / "accounts" / "Personal" / "auth.json").read_text(),
                '{"account":"new"}',
            )

    def test_add_account_restores_previous_auth_when_login_fails(self):
        with TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            runtime = root / ".runtime"
            codex_home = root / "codex-home"
            codex_home.mkdir()
            auth_path = codex_home / "auth.json"
            auth_path.write_text('{"account":"old"}')
            login_script = _write_login_script(root, "import sys\nsys.exit(7)\n")
            config = AppConfig(project_root=root, runtime_dir=runtime)

            with self.assertRaisesRegex(AddAccountError, "codex login failed"):
                add_account(
                    config,
                    "Personal",
                    codex_home=codex_home,
                    login_command=["python3", str(login_script)],
                )

            self.assertEqual(auth_path.read_text(), '{"account":"old"}')
            self.assertFalse((runtime / "accounts" / "Personal" / "auth.json").exists())


def _write_login_script(root: Path, source: str) -> Path:
    path = root / "fake_login.py"
    path.write_text(textwrap.dedent(source).lstrip())
    return path


if __name__ == "__main__":
    unittest.main()
