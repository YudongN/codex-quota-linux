from __future__ import annotations

import json
import sys
import tempfile
import textwrap
import urllib.error
import unittest
from pathlib import Path

from codex_quota.client import (
    CodexAppServerClient,
    CodexClientError,
    DirectQuotaClient,
)


class DirectQuotaClientTests(unittest.TestCase):
    def test_reads_usage_with_slot_access_token(self):
        with tempfile.TemporaryDirectory() as tempdir:
            auth_home = Path(tempdir)
            (auth_home / "auth.json").write_text(
                '{"tokens":{"access_token":"test-access-token"}}'
            )
            calls = []

            def opener(request, timeout):
                calls.append((request, timeout))
                return _FakeHttpResponse({"plan_type": "plus", "rate_limit": {}})

            result = DirectQuotaClient(
                endpoint="https://example.test/wham/usage",
                timeout_seconds=8,
                max_attempts=3,
                opener=opener,
            ).read_usage(auth_home)

        self.assertEqual(result["plan_type"], "plus")
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0][1], 8)
        self.assertEqual(
            calls[0][0].get_header("Authorization"),
            "Bearer test-access-token",
        )

    def test_retries_transient_direct_errors(self):
        with tempfile.TemporaryDirectory() as tempdir:
            auth_home = Path(tempdir)
            (auth_home / "auth.json").write_text(
                '{"tokens":{"access_token":"test-access-token"}}'
            )
            attempts = 0

            def opener(_request, timeout):
                nonlocal attempts
                del timeout
                attempts += 1
                if attempts < 3:
                    raise urllib.error.URLError("TLS handshake failed")
                return _FakeHttpResponse({"plan_type": "plus", "rate_limit": {}})

            result = DirectQuotaClient(
                endpoint="https://example.test/wham/usage",
                timeout_seconds=8,
                max_attempts=3,
                opener=opener,
            ).read_usage(auth_home)

        self.assertEqual(result["plan_type"], "plus")
        self.assertEqual(attempts, 3)


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


class _FakeHttpResponse:
    status = 200

    def __init__(self, payload):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return None

    def read(self):
        return json.dumps(self.payload).encode("utf-8")


if __name__ == "__main__":
    unittest.main()
