from __future__ import annotations

import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from .accounts import account_slot_path
from .config import AppConfig, save_config


class AddAccountError(RuntimeError):
    pass


@dataclass(frozen=True)
class AddAccountResult:
    alias: str
    auth_path: Path


def add_account(
    config: AppConfig,
    alias: str,
    *,
    codex_home: Path | None = None,
    login_command: list[str] | None = None,
) -> AddAccountResult:
    slot_home = account_slot_path(config.accounts_dir, alias)
    selected_alias = slot_home.name
    target_home = codex_home or Path.home() / ".codex"
    target_auth = target_home / "auth.json"
    target_home.mkdir(parents=True, exist_ok=True)
    config.runtime_dir.mkdir(parents=True, exist_ok=True)

    had_auth = target_auth.exists()
    previous_auth = target_auth.read_bytes() if had_auth else None
    primary_error: BaseException | None = None
    try:
        exit_code = subprocess.call(login_command or ["codex", "login"])
        if exit_code != 0:
            raise AddAccountError(f"codex login failed with exit code {exit_code}")
        if not target_auth.is_file():
            raise AddAccountError("codex login did not create auth.json")
        slot_home.mkdir(parents=True, exist_ok=True)
        slot_auth = slot_home / "auth.json"
        shutil.copy2(target_auth, slot_auth)
        os.chmod(slot_auth, 0o600)
        save_config(
            config,
            selected_alias=config.selected_alias or selected_alias,
        )
        return AddAccountResult(
            alias=selected_alias,
            auth_path=slot_auth,
        )
    except BaseException as exc:
        primary_error = exc
        raise
    finally:
        try:
            _restore_auth(target_auth, previous_auth)
        except OSError:
            if primary_error is None:
                raise


def _restore_auth(auth_path: Path, previous_auth: bytes | None) -> None:
    if previous_auth is not None:
        auth_path.write_bytes(previous_auth)
        os.chmod(auth_path, 0o600)
        return
    if auth_path.exists():
        auth_path.unlink()
