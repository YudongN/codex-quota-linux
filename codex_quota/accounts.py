from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class AccountSlot:
    alias: str
    path: Path


def account_slot_path(accounts_dir: Path, alias: str) -> Path:
    normalized = alias.strip()
    if (
        not normalized
        or normalized in {".", ".."}
        or "/" in normalized
        or "\\" in normalized
    ):
        raise ValueError("account alias must be a single directory name")
    return accounts_dir / normalized


def discover_account_slots(accounts_dir: Path) -> list[AccountSlot]:
    if not accounts_dir.exists():
        return []
    slots: list[AccountSlot] = []
    for path in sorted(accounts_dir.iterdir(), key=lambda item: item.name.lower()):
        if not path.is_dir():
            continue
        if not (path / "auth.json").is_file():
            continue
        slots.append(AccountSlot(alias=path.name, path=path))
    return slots
