from __future__ import annotations

import subprocess


def notify_switch(alias: str) -> None:
    _notify(
        'Switched to Codex account '
        f'"{alias}". Restart running Codex apps if needed.'
    )


def notify_activation_results(results) -> None:
    _notify(", ".join(_activation_result_text(result) for result in results))


def _notify(message: str) -> None:
    try:
        subprocess.Popen(
            [
                "notify-send",
                "[Codex Quota]",
                message,
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except OSError:
        return


def _activation_result_text(result) -> str:
    if result.status == "success":
        text = f'Account "{result.alias}" activated successfully'
        if result.tokens_used is not None:
            text += f" (tokens used: {result.tokens_used:,})"
        return text
    if result.status == "timeout":
        return f'Account "{result.alias}" activation timeout'
    if result.status == "failed":
        return f'Account "{result.alias}" activation failed'
    return f'Account "{result.alias}" activation {result.status}'
