# codex-quota-linux

Minimal Linux AppIndicator for watching and switching Codex account quota.

## What it shows

- Top bar: current account quota, for example `H68 · W43`.
- Menu: current account details, standby account quota, reset time, refresh, and quit.
- Status icon color follows the current account's 5h quota.

## Requirements

- Linux desktop with AppIndicator support
- `codex` CLI available on `PATH`
- Python GTK bindings:

```bash
./codex-quota doctor
```

## Usage

```bash
./codex-quota add Personal
./codex-quota add Work
./codex-quota once
./codex-quota run
```

Switch the active Codex account:

```bash
./codex-quota switch Work
```

Running Codex apps may need restart after a switch.

## Runtime Files

Project-local runtime lives in `.runtime/` and is git-ignored.

- `.runtime/config.toml`: selected account and refresh intervals.
- `.runtime/accounts/<Alias>/auth.json`: stored account credential.
- `.runtime/accounts/<Alias>/cache.json`: last quota snapshot.

Do not commit `.runtime/`. It contains account credentials.

## Tests

```bash
python3 -m unittest discover -s tests
```
