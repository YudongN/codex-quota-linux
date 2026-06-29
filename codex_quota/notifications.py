from __future__ import annotations

import subprocess


def notify_switch(alias: str) -> None:
    try:
        subprocess.Popen(
            [
                "notify-send",
                "[Codex Quota]",
                f'Switched to Codex account "{alias}". Restart running Codex apps if needed.',
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except OSError:
        return
