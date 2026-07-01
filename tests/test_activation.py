import json
import os
import subprocess
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from codex_quota.activation import activate_window
from codex_quota.activation import _codex_activation_command
from codex_quota.config import AppConfig


class ActivationTests(unittest.TestCase):
    def test_activation_command_uses_supported_exec_flags(self):
        command = _codex_activation_command(Path("/tmp/project"))

        self.assertNotIn("--ask-for-approval", command)
        self.assertIn("--ephemeral", command)
        self.assertIn("--ignore-rules", command)
        self.assertIn("--skip-git-repo-check", command)
        self.assertIn("-s", command)
        self.assertIn("read-only", command)

    def test_dry_run_selects_all_slots_without_writing_or_running(self):
        with TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            runtime = root / ".runtime"
            codex_home = root / "codex-home"
            for alias in ("Backup", "Work"):
                _write_auth(runtime / "accounts" / alias / "auth.json", marker=alias)
            _write_auth(codex_home / "auth.json", marker="main")
            config = AppConfig(project_root=root, runtime_dir=runtime)
            calls = []

            results = activate_window(
                config,
                all_accounts=True,
                aliases=[],
                dry_run=True,
                codex_home=codex_home,
                runner=lambda command, timeout: calls.append((command, timeout)),
            )

            self.assertEqual([result.alias for result in results], ["Backup", "Work"])
            self.assertEqual([result.status for result in results], ["dry-run", "dry-run"])
            self.assertEqual(calls, [])
            self.assertEqual(_auth_marker(codex_home / "auth.json"), "main")

    def test_activate_aliases_restores_original_auth_and_preserves_selected_alias(self):
        with TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            runtime = root / ".runtime"
            codex_home = root / "codex-home"
            _write_auth(runtime / "accounts" / "Work" / "auth.json", marker="work")
            _write_auth(runtime / "accounts" / "Backup" / "auth.json", marker="backup")
            _write_auth(codex_home / "auth.json", marker="main")
            config = AppConfig(
                project_root=root,
                runtime_dir=runtime,
                selected_alias="Work",
                activate_timeout_seconds=12,
            )
            calls = []

            def runner(command, timeout):
                calls.append((command, timeout, _auth_marker(codex_home / "auth.json")))
                return subprocess.CompletedProcess(command, 0, stdout="OK\n", stderr="")

            results = activate_window(
                config,
                all_accounts=False,
                aliases=["Backup", "Work"],
                dry_run=False,
                codex_home=codex_home,
                runner=runner,
            )

            self.assertEqual([result.status for result in results], ["success", "success"])
            self.assertEqual([call[2] for call in calls], ["backup", "work"])
            self.assertTrue(all(call[1] == 12 for call in calls))
            self.assertEqual(_auth_marker(codex_home / "auth.json"), "main")
            self.assertEqual(_auth_mode(codex_home / "auth.json"), "0o600")
            self.assertFalse((runtime / "config.toml").exists())

    def test_activate_restores_auth_after_runner_failure(self):
        with TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            runtime = root / ".runtime"
            codex_home = root / "codex-home"
            _write_auth(runtime / "accounts" / "Work" / "auth.json", marker="work")
            _write_auth(codex_home / "auth.json", marker="main")
            config = AppConfig(project_root=root, runtime_dir=runtime)

            def runner(command, timeout):
                raise RuntimeError("boom")

            results = activate_window(
                config,
                all_accounts=False,
                aliases=["Work"],
                dry_run=False,
                codex_home=codex_home,
                runner=runner,
            )

            self.assertEqual(results[0].status, "failed")
            self.assertEqual(_auth_marker(codex_home / "auth.json"), "main")

    def test_activate_restores_missing_original_auth_to_missing(self):
        with TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            runtime = root / ".runtime"
            codex_home = root / "codex-home"
            codex_home.mkdir()
            _write_auth(runtime / "accounts" / "Work" / "auth.json", marker="work")
            config = AppConfig(project_root=root, runtime_dir=runtime)

            results = activate_window(
                config,
                all_accounts=False,
                aliases=["Work"],
                dry_run=False,
                codex_home=codex_home,
                runner=lambda command, timeout: subprocess.CompletedProcess(command, 0),
            )

            self.assertEqual(results[0].status, "success")
            self.assertFalse((codex_home / "auth.json").exists())

    def test_activate_reports_timeout_and_restores_auth(self):
        with TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            runtime = root / ".runtime"
            codex_home = root / "codex-home"
            _write_auth(runtime / "accounts" / "Work" / "auth.json", marker="work")
            _write_auth(codex_home / "auth.json", marker="main")
            config = AppConfig(project_root=root, runtime_dir=runtime)

            def runner(command, timeout):
                raise subprocess.TimeoutExpired(command, timeout)

            results = activate_window(
                config,
                all_accounts=False,
                aliases=["Work"],
                dry_run=False,
                codex_home=codex_home,
                runner=runner,
            )

            self.assertEqual(results[0].status, "timeout")
            self.assertEqual(_auth_marker(codex_home / "auth.json"), "main")


def _write_auth(path, *, marker):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"marker": marker, "tokens": {}}))
    os.chmod(path, 0o600)


def _auth_marker(path):
    return json.loads(path.read_text())["marker"]


def _auth_mode(path):
    return oct(path.stat().st_mode & 0o777)


if __name__ == "__main__":
    unittest.main()
