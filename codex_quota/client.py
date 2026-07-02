from __future__ import annotations

import json
import os
import select
import socket
import subprocess
import ssl
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any


DIRECT_USAGE_ENDPOINT = "https://chatgpt.com/backend-api/wham/usage"
DIRECT_RESET_CREDITS_ENDPOINT = (
    "https://chatgpt.com/backend-api/wham/rate-limit-reset-credits"
)


class CodexClientError(RuntimeError):
    pass


class DirectQuotaError(RuntimeError):
    pass


class DirectQuotaTransientError(DirectQuotaError):
    pass


class DirectQuotaAuthError(DirectQuotaError):
    pass


class DirectQuotaSchemaError(DirectQuotaError):
    pass


class DirectResetCreditsError(RuntimeError):
    pass


class DirectResetCreditsTransientError(DirectResetCreditsError):
    pass


class DirectResetCreditsAuthError(DirectResetCreditsError):
    pass


class DirectResetCreditsSchemaError(DirectResetCreditsError):
    pass


@dataclass(frozen=True)
class RpcResult:
    result: dict[str, Any]


class DirectQuotaClient:
    def __init__(
        self,
        *,
        endpoint: str = DIRECT_USAGE_ENDPOINT,
        timeout_seconds: float = 8.0,
        max_attempts: int = 3,
        opener: Any = None,
    ):
        self.endpoint = endpoint
        self.timeout_seconds = timeout_seconds
        self.max_attempts = max(1, max_attempts)
        self.opener = opener or urllib.request.urlopen

    def read_usage(self, auth_home: Path) -> dict[str, Any]:
        token = _read_access_token(auth_home / "auth.json")
        last_error: DirectQuotaTransientError | None = None
        for _attempt in range(self.max_attempts):
            try:
                return self._read_once(token)
            except DirectQuotaTransientError as exc:
                last_error = exc
        raise last_error or DirectQuotaTransientError("quota request failed")

    def _read_once(self, token: str) -> dict[str, Any]:
        request = urllib.request.Request(
            self.endpoint,
            headers={
                "Accept": "application/json",
                "Authorization": f"Bearer {token}",
            },
            method="GET",
        )
        try:
            with self.opener(request, timeout=self.timeout_seconds) as response:
                body = response.read()
                status = getattr(response, "status", None)
        except urllib.error.HTTPError as exc:
            body = exc.read()
            raise _direct_http_error(exc.code, body) from exc
        except (
            urllib.error.URLError,
            TimeoutError,
            socket.timeout,
            ssl.SSLError,
            ConnectionError,
        ) as exc:
            raise DirectQuotaTransientError("quota request failed") from exc
        if isinstance(status, int) and status >= 400:
            raise _direct_http_error(status, body)
        try:
            payload = json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise DirectQuotaSchemaError("Backend changed") from exc
        if not isinstance(payload, dict):
            raise DirectQuotaSchemaError("Backend changed")
        if _payload_looks_auth_failure(payload):
            raise DirectQuotaAuthError("direct quota auth failed")
        return payload


class DirectResetCreditsClient:
    def __init__(
        self,
        *,
        endpoint: str = DIRECT_RESET_CREDITS_ENDPOINT,
        timeout_seconds: float = 8.0,
        max_attempts: int = 3,
        opener: Any = None,
    ):
        self.endpoint = endpoint
        self.timeout_seconds = timeout_seconds
        self.max_attempts = max(1, max_attempts)
        self.opener = opener or urllib.request.urlopen

    def read_reset_credits(self, auth_home: Path) -> dict[str, Any]:
        try:
            token = _read_access_token(auth_home / "auth.json")
        except DirectQuotaAuthError as exc:
            raise DirectResetCreditsAuthError("direct reset credits auth failed") from exc
        last_error: DirectResetCreditsTransientError | None = None
        for _attempt in range(self.max_attempts):
            try:
                return self._read_once(token)
            except DirectResetCreditsTransientError as exc:
                last_error = exc
        raise last_error or DirectResetCreditsTransientError("reset credits request failed")

    def _read_once(self, token: str) -> dict[str, Any]:
        request = urllib.request.Request(
            self.endpoint,
            headers={
                "Accept": "application/json",
                "Authorization": f"Bearer {token}",
            },
            method="GET",
        )
        try:
            with self.opener(request, timeout=self.timeout_seconds) as response:
                body = response.read()
                status = getattr(response, "status", None)
        except urllib.error.HTTPError as exc:
            body = exc.read()
            raise _direct_reset_credits_http_error(exc.code, body) from exc
        except (
            urllib.error.URLError,
            TimeoutError,
            socket.timeout,
            ssl.SSLError,
            ConnectionError,
        ) as exc:
            raise DirectResetCreditsTransientError("reset credits request failed") from exc
        if isinstance(status, int) and status >= 400:
            raise _direct_reset_credits_http_error(status, body)
        try:
            payload = json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise DirectResetCreditsSchemaError("Backend changed") from exc
        if not isinstance(payload, dict):
            raise DirectResetCreditsSchemaError("Backend changed")
        if _payload_looks_auth_failure(payload):
            raise DirectResetCreditsAuthError("direct reset credits auth failed")
        return payload


class CodexAppServerClient:
    def __init__(
        self,
        command: list[str] | None = None,
        timeout_seconds: float = 20.0,
        codex_home: Path | None = None,
    ):
        self.command = command or ["codex", "app-server", "--stdio"]
        self.timeout_seconds = timeout_seconds
        self.codex_home = codex_home

    def read_rate_limits(self) -> dict[str, Any]:
        return self._request("account/rateLimits/read", None).result

    def _request(self, method: str, params: Any) -> RpcResult:
        env = None
        if self.codex_home is not None:
            env = os.environ.copy()
            env["CODEX_HOME"] = str(self.codex_home)
        process = subprocess.Popen(
            self.command,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
            env=env,
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


def _read_access_token(auth_path: Path) -> str:
    try:
        data = json.loads(auth_path.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        raise DirectQuotaAuthError("direct quota auth failed") from exc
    if not isinstance(data, dict):
        raise DirectQuotaAuthError("direct quota auth failed")
    tokens = data.get("tokens")
    access_token = tokens.get("access_token") if isinstance(tokens, dict) else None
    if not isinstance(access_token, str) or not access_token:
        raise DirectQuotaAuthError("direct quota auth failed")
    return access_token


def _direct_http_error(status: int, body: bytes) -> DirectQuotaError:
    if status in {401, 403} or _body_looks_auth_failure(body):
        return DirectQuotaAuthError("direct quota auth failed")
    if status in {408, 429} or status >= 500:
        return DirectQuotaTransientError("quota request failed")
    return DirectQuotaSchemaError("Backend changed")


def _direct_reset_credits_http_error(
    status: int,
    body: bytes,
) -> DirectResetCreditsError:
    if status in {401, 403} or _body_looks_auth_failure(body):
        return DirectResetCreditsAuthError("direct reset credits auth failed")
    if status in {408, 429} or status >= 500:
        return DirectResetCreditsTransientError("reset credits request failed")
    return DirectResetCreditsSchemaError("Backend changed")


def _body_looks_auth_failure(body: bytes) -> bool:
    text = body.decode("utf-8", errors="ignore").lower()
    return any(word in text for word in ("refresh", "token", "unauthorized", "auth"))


def _payload_looks_auth_failure(payload: dict[str, Any]) -> bool:
    for field in ("error", "message", "detail"):
        value = payload.get(field)
        if isinstance(value, str) and _body_looks_auth_failure(value.encode("utf-8")):
            return True
    return False


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
