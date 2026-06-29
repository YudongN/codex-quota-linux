from __future__ import annotations

import shutil
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path


_KEEP_FILES = {"auth.json", "cache.json"}


@dataclass(frozen=True)
class LegacyMigrationReport:
    migrated_accounts: list[str]
    conversation_candidates: list[str]
    archive_root: Path | None


def migrate_legacy_homes(
    runtime_dir: Path,
    *,
    timestamp: str | None = None,
) -> LegacyMigrationReport:
    accounts_dir = runtime_dir / "accounts"
    if not accounts_dir.exists():
        return LegacyMigrationReport([], [], None)

    timestamp = timestamp or datetime.now().astimezone().strftime("%Y%m%d-%H%M%S")
    archive_root = runtime_dir / "legacy-codex-homes" / timestamp
    migrated_accounts: list[str] = []
    conversation_candidates: list[str] = []

    for account_dir in sorted(accounts_dir.iterdir(), key=lambda item: item.name.lower()):
        if not account_dir.is_dir():
            continue
        movable = [item for item in account_dir.iterdir() if item.name not in _KEEP_FILES]
        if not movable:
            continue
        account_archive = archive_root / account_dir.name
        account_archive.mkdir(parents=True, exist_ok=True)
        migrated_accounts.append(account_dir.name)
        for item in movable:
            relative = f"{account_dir.name}/{item.name}"
            if _looks_like_conversation_state(item):
                conversation_candidates.append(relative)
            shutil.move(str(item), str(account_archive / item.name))

    if not migrated_accounts:
        return LegacyMigrationReport([], [], None)
    return LegacyMigrationReport(migrated_accounts, conversation_candidates, archive_root)


def _looks_like_conversation_state(path: Path) -> bool:
    return (
        path.name.startswith("state_")
        or path.name.startswith("logs_")
        or path.name.startswith("rollout-")
    )
