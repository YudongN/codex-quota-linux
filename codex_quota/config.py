from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class AppConfig:
    project_root: Path
    runtime_dir: Path
    current_alias: str = "Main"
    refresh_interval_seconds: int = 60

    @property
    def accounts_dir(self) -> Path:
        return self.runtime_dir / "accounts"


def load_config() -> AppConfig:
    root = Path(__file__).resolve().parents[1]
    runtime_dir = root / ".runtime"
    config_path = runtime_dir / "config.toml"
    values: dict[str, object] = {}
    if config_path.exists():
        values = _read_simple_config(config_path)
    alias = values.get("current_alias", "Main")
    interval = values.get("refresh_interval_seconds", 60)
    return AppConfig(
        project_root=root,
        runtime_dir=runtime_dir,
        current_alias=alias if isinstance(alias, str) and alias else "Main",
        refresh_interval_seconds=interval if isinstance(interval, int) else 60,
    )


def _read_simple_config(path: Path) -> dict[str, object]:
    values: dict[str, object] = {}
    for raw_line in path.read_text().splitlines():
        line = raw_line.split("#", 1)[0].strip()
        if not line or "=" not in line:
            continue
        key, value = [part.strip() for part in line.split("=", 1)]
        if value.startswith('"') and value.endswith('"'):
            values[key] = value[1:-1]
        else:
            try:
                values[key] = int(value)
            except ValueError:
                values[key] = value
    return values
