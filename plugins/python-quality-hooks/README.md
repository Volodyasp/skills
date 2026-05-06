# python-quality-hooks

Two `PostToolUse` hooks that run after Claude touches a Python file. Both are **non-blocking** — they print findings to the chat so Claude can react, but never abort the tool call.

## What runs

### `Edit` → check only

After `Edit` on a `*.py` file:

- **`ruff check --select=F,B,E9,E71,S,ASYNC,DTZ --no-fix`** — bugs and security only:
  - `F` — pyflakes (undefined names, unused imports/vars)
  - `B` — bugbear (likely-bug patterns)
  - `E9` — runtime / syntax errors
  - `E71` — comparison statements
  - `S` — bandit-style security
  - `ASYNC` — async/await pitfalls
  - `DTZ` — naive datetime
- **`mypy --ignore-missing-imports --follow-imports=silent`** — type errors

No auto-fix — existing files have a diff Claude is reading, and reformatting under it leads to confused edits.

### `Write` → fix then check

After `Write` on a `*.py` file:

1. **`ruff check --select=I --fix`** — auto-sort imports (isort)
2. **`ruff format`** — full formatting
3. Same `ruff` bugs-only check + `mypy` as above

Auto-fixes are safe here because the file was just written from scratch — no existing edit context to disturb.

## Why two matchers

A new file (`Write`) has no surrounding diff, so we can format it freely. An edit (`Edit`) is a surgical change to an existing file — running `ruff format` would rewrite lines Claude isn't expecting and produce phantom diffs in the next tool call. Symmetric tooling, asymmetric application.

## Requirements

The hooks call `jq`, `ruff`, and `mypy` from your `PATH`. If any of them are missing, that step is silently skipped (the hook still exits 0). To install:

```bash
# macOS / Linux
brew install jq
uv tool install ruff
uv tool install mypy
```

Project-local installs (`.venv/bin/ruff`) are not auto-detected — the hook uses whatever is on `PATH` at the time Claude runs it. If you want per-project pins, run Claude with the venv activated, or wrap the calls (e.g. `uv run ruff`) by editing the scripts.

## Configuration

The rule sets and mypy flags are hardcoded inside `hooks/check-python-edit.sh` and `hooks/check-python-write.sh`. Edit those files to change selectors. There is no separate config file.

If you want stricter rules in some project, fork the plugin or override locally in `~/.claude/settings.json`.

## Install

```bash
claude plugin marketplace add Volodyasp/skills
claude plugin install python-quality-hooks@skills
```

Restart Claude Code after install. Hooks activate automatically.

## Why hooks instead of pre-commit

Pre-commit runs at commit time — hours after Claude wrote the bug. PostToolUse runs **immediately** after the file is saved, so feedback lands in the same conversation turn and Claude can self-correct without you noticing the round-trip.

For projects with a real CI pipeline, you still want pre-commit / CI as the source of truth. These hooks are an early-warning layer for the AI authoring loop, not a replacement for it.
