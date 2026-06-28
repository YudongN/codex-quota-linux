from __future__ import annotations

import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

from codex_quota.client import CodexAppServerClient, CodexClientError


class CodexAppServerClientTests(unittest.TestCase):
    def test_reads_rate_limits_from_stdio_jsonrpc(self):
        script = _write_fake_server(
            """
            import json
            import sys

            for _ in range(2):
                request = json.loads(sys.stdin.readline())
                if request["id"] == 1:
                    print(json.dumps({"jsonrpc": "2.0", "id": 1, "result": {"ok": True}}), flush=True)
                elif request["id"] == 2:
                    print(json.dumps({"jsonrpc": "2.0", "method": "remoteControl/status/changed", "params": {}}), flush=True)
                    print(json.dumps({
                        "jsonrpc": "2.0",
                        "id": 2,
                        "result": {
                            "rateLimitsByLimitId": {
                                "codex": {
                                    "planType": "plus",
                                    "primary": {"usedPercent": 32, "windowDurationMins": 300},
                                    "secondary": {"usedPercent": 57, "windowDurationMins": 10080}
                                }
                            },
                            "rateLimits": {}
                        }
                    }), flush=True)
            """
        )

        result = CodexAppServerClient(
            command=[sys.executable, str(script)],
            timeout_seconds=2,
        ).read_rate_limits()

        codex = result["rateLimitsByLimitId"]["codex"]
        self.assertEqual(codex["planType"], "plus")
        self.assertEqual(codex["primary"]["usedPercent"], 32)

    def test_raises_app_server_error_message(self):
        script = _write_fake_server(
            """
            import json
            import sys

            for _ in range(2):
                request = json.loads(sys.stdin.readline())
                if request["id"] == 1:
                    print(json.dumps({"jsonrpc": "2.0", "id": 1, "result": {}}), flush=True)
                elif request["id"] == 2:
                    print(json.dumps({
                        "jsonrpc": "2.0",
                        "id": 2,
                        "error": {"message": "usage endpoint failed"}
                    }), flush=True)
            """
        )

        with self.assertRaisesRegex(CodexClientError, "usage endpoint failed"):
            CodexAppServerClient(
                command=[sys.executable, str(script)],
                timeout_seconds=2,
            ).read_rate_limits()

    def test_passes_codex_home_to_app_server_environment(self):
        script = _write_fake_server(
            """
            import json
            import os
            import sys

            for _ in range(2):
                request = json.loads(sys.stdin.readline())
                if request["id"] == 1:
                    print(json.dumps({"jsonrpc": "2.0", "id": 1, "result": {}}), flush=True)
                elif request["id"] == 2:
                    print(json.dumps({
                        "jsonrpc": "2.0",
                        "id": 2,
                        "result": {"codex_home": os.environ.get("CODEX_HOME")}
                    }), flush=True)
            """
        )

        with tempfile.TemporaryDirectory() as tempdir:
            result = CodexAppServerClient(
                command=[sys.executable, str(script)],
                timeout_seconds=2,
                codex_home=Path(tempdir),
            ).read_rate_limits()

        self.assertEqual(result["codex_home"], tempdir)


def _write_fake_server(source: str) -> Path:
    tempdir = tempfile.TemporaryDirectory()
    path = Path(tempdir.name) / "fake_codex_app_server.py"
    path.write_text(textwrap.dedent(source).lstrip())
    _TEMP_DIRS.append(tempdir)
    return path


_TEMP_DIRS: list[tempfile.TemporaryDirectory[str]] = []


if __name__ == "__main__":
    unittest.main()
