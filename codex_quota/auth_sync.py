from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any


def sync_refreshed_auth(*, source: Path, target: Path) -> bool:
    try:
        source_bytes = source.read_bytes()
        target_bytes = target.read_bytes()
    except OSError:
        return False
    if source_bytes == target_bytes:
        return False

    source_payload = _load_auth(source_bytes)
    target_payload = _load_auth(target_bytes)
    if source_payload is None or target_payload is None:
        return False

    source_account_id = _token_value(source_payload, "account_id")
    target_account_id = _token_value(target_payload, "account_id")
    source_access_token = _token_value(source_payload, "access_token")
    source_refresh_token = _token_value(source_payload, "refresh_token")
    if not source_account_id or source_account_id != target_account_id:
        return False
    if not source_access_token:
        return False
    if not source_refresh_token:
        return False

    try:
        _atomic_write_auth(target, source_bytes)
    except OSError:
        return False
    return True


def _load_auth(payload: bytes) -> dict[str, Any] | None:
    try:
        data = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def _token_value(payload: dict[str, Any], field: str) -> str | None:
    tokens = payload.get("tokens")
    if not isinstance(tokens, dict):
        return None
    value = tokens.get(field)
    return value if isinstance(value, str) and value else None


def _atomic_write_auth(target: Path, payload: bytes) -> None:
    fd, temp_name = tempfile.mkstemp(
        prefix=f".{target.name}.tmp-",
        dir=target.parent,
    )
    temp_path = Path(temp_name)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(payload)
        os.chmod(temp_path, 0o600)
        os.replace(temp_path, target)
        os.chmod(target, 0o600)
    finally:
        if temp_path.exists():
            temp_path.unlink()
