from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class AppConfig:
    project_root: Path
    runtime_dir: Path
    selected_alias: str = ""
    active_refresh_interval_seconds: int = 120
    standby_refresh_interval_seconds: int = 600
    direct_max_attempts: int = 3
    direct_timeout_seconds: int = 8
    activate_timeout_seconds: int = 90

    @property
    def accounts_dir(self) -> Path:
        return self.runtime_dir / "accounts"


def load_config(root: Path | None = None) -> AppConfig:
    root = root or Path(__file__).resolve().parents[1]
    runtime_dir = root / ".runtime"
    config_path = runtime_dir / "config.toml"
    values: dict[str, object] = {}
    if config_path.exists():
        values = _read_simple_config(config_path)
    alias = values.get("selected_alias")
    if not isinstance(alias, str):
        alias = values.get("current_alias")
    config = AppConfig(
        project_root=root,
        runtime_dir=runtime_dir,
        selected_alias=alias if isinstance(alias, str) else "",
        active_refresh_interval_seconds=_int_value(
            values.get("active_refresh_interval_seconds"),
            120,
        ),
        standby_refresh_interval_seconds=_int_value(
            values.get("standby_refresh_interval_seconds"),
            600,
        ),
        direct_max_attempts=_int_value(values.get("direct_max_attempts"), 3),
        direct_timeout_seconds=_int_value(values.get("direct_timeout_seconds"), 8),
        activate_timeout_seconds=_int_value(values.get("activate_timeout_seconds"), 90),
    )
    save_config(config)
    return config


def save_config(config: AppConfig, *, selected_alias: str | None = None) -> None:
    config.runtime_dir.mkdir(parents=True, exist_ok=True)
    path = config.runtime_dir / "config.toml"
    alias = selected_alias if selected_alias is not None else config.selected_alias
    text = (
        f"selected_alias = {json.dumps(alias)}\n"
        f"active_refresh_interval_seconds = {config.active_refresh_interval_seconds}\n"
        f"standby_refresh_interval_seconds = {config.standby_refresh_interval_seconds}\n"
        f"direct_max_attempts = {config.direct_max_attempts}\n"
        f"direct_timeout_seconds = {config.direct_timeout_seconds}\n"
        f"activate_timeout_seconds = {config.activate_timeout_seconds}\n"
    )
    temp_path = path.with_name(".config.toml.tmp")
    temp_path.write_text(text)
    temp_path.replace(path)


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


def _int_value(value: object, default: int) -> int:
    return value if isinstance(value, int) and value > 0 else default
