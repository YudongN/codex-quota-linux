from __future__ import annotations

from .auth_info import read_account_info
from .client import CodexAppServerClient, CodexClientError
from .config import AppConfig
from .quota import QuotaSnapshot, failed_snapshot, parse_rate_limits, save_cache


def fetch_snapshot(config: AppConfig) -> QuotaSnapshot:
    account = read_account_info()
    cache_path = config.runtime_dir / "cache.json"
    try:
        response = CodexAppServerClient().read_rate_limits()
        snapshot = parse_rate_limits(
            response,
            alias=config.current_alias,
            email=account.email,
        )
        save_cache(cache_path, snapshot)
        return snapshot
    except CodexClientError as exc:
        return failed_snapshot(
            alias=config.current_alias,
            email=account.email,
            error=str(exc),
            cache_path=cache_path,
        )
