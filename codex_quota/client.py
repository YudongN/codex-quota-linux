from __future__ import annotations

import json
import select
import subprocess
import time
from dataclasses import dataclass
from typing import Any


class CodexClientError(RuntimeError):
    pass


@dataclass(frozen=True)
class RpcResult:
    result: dict[str, Any]


class CodexAppServerClient:
    def __init__(self, command: list[str] | None = None, timeout_seconds: float = 20.0):
        self.command = command or ["codex", "app-server", "--stdio"]
        self.timeout_seconds = timeout_seconds

    def read_rate_limits(self) -> dict[str, Any]:
        return self._request("account/rateLimits/read", None).result

    def _request(self, method: str, params: Any) -> RpcResult:
        process = subprocess.Popen(
            self.command,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
        )
        try:
            assert process.stdin is not None
            self._send(process, 1, "initialize", _initialize_params())
            self._send(process, 2, method, params)
            return self._read_response(process, 2)
        finally:
            _stop_process(process)

    @staticmethod
    def _send(
        process: subprocess.Popen[str], request_id: int, method: str, params: Any
    ) -> None:
        assert process.stdin is not None
        message = {
            "jsonrpc": "2.0",
            "id": request_id,
            "method": method,
            "params": params,
        }
        process.stdin.write(json.dumps(message, separators=(",", ":")) + "\n")
        process.stdin.flush()

    def _read_response(
        self, process: subprocess.Popen[str], request_id: int
    ) -> RpcResult:
        assert process.stdout is not None
        assert process.stderr is not None
        deadline = time.monotonic() + self.timeout_seconds
        stderr_lines: list[str] = []
        while time.monotonic() < deadline:
            readable, _, _ = select.select(
                [process.stdout, process.stderr], [], [], 0.25
            )
            for stream in readable:
                line = stream.readline()
                if not line:
                    continue
                if stream is process.stderr:
                    stderr_lines.append(line.strip())
                    continue
                payload = _loads_json_line(line)
                if payload.get("id") != request_id:
                    continue
                if "error" in payload:
                    error = payload["error"]
                    message = error.get("message") if isinstance(error, dict) else error
                    raise CodexClientError(str(message))
                result = payload.get("result")
                if not isinstance(result, dict):
                    raise CodexClientError("Codex app-server returned a non-object result")
                return RpcResult(result)
        detail = f" stderr={stderr_lines[-1]}" if stderr_lines else ""
        raise CodexClientError(f"timed out waiting for {request_id}{detail}")


def _initialize_params() -> dict[str, Any]:
    return {
        "clientInfo": {"name": "codex-quota-linux", "version": "0.1.0"},
        "capabilities": {},
    }


def _loads_json_line(line: str) -> dict[str, Any]:
    try:
        payload = json.loads(line)
    except json.JSONDecodeError as exc:
        raise CodexClientError(f"invalid JSON from Codex app-server: {exc}") from exc
    if not isinstance(payload, dict):
        raise CodexClientError("Codex app-server returned a non-object JSON message")
    return payload


def _stop_process(process: subprocess.Popen[str]) -> None:
    try:
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=2)
    finally:
        for stream in (process.stdin, process.stdout, process.stderr):
            if stream is not None:
                stream.close()
