from __future__ import annotations

import base64
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class AccountInfo:
    email: str | None = None
    name: str | None = None


def read_account_info(codex_home: Path | None = None) -> AccountInfo:
    home = codex_home or Path.home() / ".codex"
    auth_path = home / "auth.json"
    try:
        data = _read_auth_json(auth_path)
        id_token = data.get("tokens", {}).get("id_token")
        if not isinstance(id_token, str):
            return AccountInfo()
        payload = _decode_jwt_payload(id_token)
        email = payload.get("email")
        name = payload.get("name")
        return AccountInfo(
            email=email if isinstance(email, str) else None,
            name=name if isinstance(name, str) else None,
        )
    except Exception:
        return AccountInfo()


def _read_auth_json(auth_path: Path) -> dict[str, Any]:
    data = json.loads(auth_path.read_text())
    return data if isinstance(data, dict) else {}


def _decode_jwt_payload(token: str) -> dict[str, Any]:
    parts = token.split(".")
    if len(parts) < 2:
        return {}
    payload = parts[1] + "=" * (-len(parts[1]) % 4)
    decoded = base64.urlsafe_b64decode(payload.encode("ascii"))
    parsed = json.loads(decoded)
    return parsed if isinstance(parsed, dict) else {}
