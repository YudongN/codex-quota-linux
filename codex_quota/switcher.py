from __future__ import annotations

import fcntl
import os
import shutil
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from .accounts import account_slot_path
from .config import AppConfig, save_config


class SwitchError(RuntimeError):
    pass


@dataclass(frozen=True)
class SwitchResult:
    alias: str
    auth_path: Path
    backup_path: Path | None
    captured_current_path: Path | None


def switch_account(
    config: AppConfig,
    alias: str,
    *,
    codex_home: Path | None = None,
) -> SwitchResult:
    slot_home = account_slot_path(config.accounts_dir, alias)
    selected_alias = slot_home.name
    slot_auth = slot_home / "auth.json"
    if not slot_auth.is_file():
        raise SwitchError(f"account slot '{selected_alias}' does not have auth.json")

    target_home = codex_home or Path.home() / ".codex"
    target_auth = target_home / "auth.json"
    target_home.mkdir(parents=True, exist_ok=True)
    config.runtime_dir.mkdir(parents=True, exist_ok=True)

    lock_path = config.runtime_dir / "app.lock"
    with lock_path.open("w") as lock_file:
        fcntl.flock(lock_file, fcntl.LOCK_EX)
        captured = _capture_current_slot(config, target_auth, selected_alias)
        backup = _backup_current_auth(config, target_auth)
        _replace_auth(source=slot_auth, target=target_auth)
        save_config(config, current_alias=selected_alias)
        return SwitchResult(
            alias=selected_alias,
            auth_path=target_auth,
            backup_path=backup,
            captured_current_path=captured,
        )


def _capture_current_slot(
    config: AppConfig,
    target_auth: Path,
    next_alias: str,
) -> Path | None:
    if config.current_alias == next_alias or not target_auth.exists():
        return None
    current_home = account_slot_path(config.accounts_dir, config.current_alias)
    current_auth = current_home / "auth.json"
    current_home.mkdir(parents=True, exist_ok=True)
    shutil.copy2(target_auth, current_auth)
    os.chmod(current_auth, 0o600)
    return current_auth


def _backup_current_auth(config: AppConfig, target_auth: Path) -> Path | None:
    if not target_auth.exists():
        return None
    backups_dir = config.runtime_dir / "backups"
    backups_dir.mkdir(parents=True, exist_ok=True)
    os.chmod(backups_dir, 0o700)
    timestamp = datetime.now().astimezone().strftime("%Y%m%d-%H%M%S")
    backup_path = backups_dir / f"auth-{timestamp}.json"
    suffix = 1
    while backup_path.exists():
        backup_path = backups_dir / f"auth-{timestamp}-{suffix}.json"
        suffix += 1
    shutil.copy2(target_auth, backup_path)
    os.chmod(backup_path, 0o600)
    return backup_path


def _replace_auth(*, source: Path, target: Path) -> None:
    temp_path = target.with_name(f".{target.name}.tmp-{os.getpid()}")
    try:
        shutil.copy2(source, temp_path)
        os.chmod(temp_path, 0o600)
        os.replace(temp_path, target)
        os.chmod(target, 0o600)
    finally:
        if temp_path.exists():
            temp_path.unlink()
