from __future__ import annotations

import fcntl
import os
import re
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from .accounts import AccountSlot, account_slot_path, discover_account_slots
from .auth_sync import sync_refreshed_auth
from .config import AppConfig


ACTIVATION_PROMPT = "Reply exactly: OK."


class ActivationError(RuntimeError):
    pass


@dataclass(frozen=True)
class ActivationResult:
    alias: str
    status: str
    tokens_used: int | None = None


Runner = Callable[[list[str], int], subprocess.CompletedProcess[str]]


def activate_window(
    config: AppConfig,
    *,
    all_accounts: bool,
    aliases: list[str],
    dry_run: bool = False,
    timeout_seconds: int | None = None,
    codex_home: Path | None = None,
    runner: Runner | None = None,
) -> list[ActivationResult]:
    slots = _select_slots(config, all_accounts=all_accounts, aliases=aliases)
    if dry_run:
        return [ActivationResult(alias=slot.alias, status="dry-run") for slot in slots]

    timeout = timeout_seconds or config.activate_timeout_seconds
    target_home = codex_home or Path.home() / ".codex"
    target_auth = target_home / "auth.json"
    run = runner or _run_codex_exec

    config.runtime_dir.mkdir(parents=True, exist_ok=True)
    lock_path = config.runtime_dir / "app.lock"
    with lock_path.open("w") as lock_file:
        fcntl.flock(lock_file, fcntl.LOCK_EX)
        original = _AuthBackup.capture(target_auth)
        try:
            return [
                _activate_slot(
                    config,
                    slot=slot,
                    target_auth=target_auth,
                    timeout_seconds=timeout,
                    runner=run,
                )
                for slot in slots
            ]
        finally:
            original.restore(target_auth)


def _select_slots(
    config: AppConfig,
    *,
    all_accounts: bool,
    aliases: list[str],
) -> list[AccountSlot]:
    if all_accounts and aliases:
        raise ActivationError("use --all or --alias, not both")
    if all_accounts:
        slots = discover_account_slots(config.accounts_dir)
        if not slots:
            raise ActivationError("no account slots found")
        return slots
    if not aliases:
        raise ActivationError("choose --all or at least one --alias")
    return [_slot_for_alias(config, alias) for alias in aliases]


def _slot_for_alias(config: AppConfig, alias: str) -> AccountSlot:
    slot_home = account_slot_path(config.accounts_dir, alias)
    auth_path = slot_home / "auth.json"
    if not auth_path.is_file():
        raise ActivationError(f"account slot '{slot_home.name}' does not have auth.json")
    return AccountSlot(alias=slot_home.name, path=slot_home)


def _activate_slot(
    config: AppConfig,
    *,
    slot: AccountSlot,
    target_auth: Path,
    timeout_seconds: int,
    runner: Runner,
) -> ActivationResult:
    slot_auth = slot.path / "auth.json"
    _write_auth_bytes(target_auth, slot_auth.read_bytes())
    command = _codex_activation_command(config.project_root)
    try:
        completed = runner(command, timeout_seconds)
    except subprocess.TimeoutExpired:
        return ActivationResult(alias=slot.alias, status="timeout")
    except Exception:
        return ActivationResult(alias=slot.alias, status="failed")
    tokens_used = _parse_tokens_used(completed)
    if completed.returncode != 0:
        return ActivationResult(
            alias=slot.alias,
            status="failed",
            tokens_used=tokens_used,
        )
    sync_refreshed_auth(source=target_auth, target=slot_auth)
    return ActivationResult(
        alias=slot.alias,
        status="success",
        tokens_used=tokens_used,
    )


def _codex_activation_command(_project_root: Path) -> list[str]:
    return [
        "codex",
        "exec",
        "--ephemeral",
        "--ignore-user-config",
        "--ignore-rules",
        "--skip-git-repo-check",
        "-m",
        "gpt-5.4-mini",
        "-c",
        'model_reasoning_effort="low"',
        "-s",
        "read-only",
        "-C",
        tempfile.gettempdir(),
        ACTIVATION_PROMPT,
    ]


def _run_codex_exec(
    command: list[str],
    timeout_seconds: int,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        timeout=timeout_seconds,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )


def _parse_tokens_used(completed: subprocess.CompletedProcess[str]) -> int | None:
    text = "\n".join(part for part in (completed.stdout, completed.stderr) if part)
    match = re.search(r"tokens used\s*:?\s*([0-9][0-9,]*)", text, re.IGNORECASE)
    if match is None:
        return None
    return int(match.group(1).replace(",", ""))


@dataclass(frozen=True)
class _AuthBackup:
    existed: bool
    payload: bytes | None = None

    @classmethod
    def capture(cls, auth_path: Path) -> _AuthBackup:
        try:
            return cls(existed=True, payload=auth_path.read_bytes())
        except FileNotFoundError:
            return cls(existed=False)

    def restore(self, auth_path: Path) -> None:
        if self.existed:
            assert self.payload is not None
            _write_auth_bytes(auth_path, self.payload)
            return
        try:
            auth_path.unlink()
        except FileNotFoundError:
            pass


def _write_auth_bytes(target: Path, payload: bytes) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=f".{target.name}.tmp-", dir=target.parent)
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
