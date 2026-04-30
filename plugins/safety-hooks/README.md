# safety-hooks

Safety nets for AI-assisted development. Two `PreToolUse` hooks:

- **`block-dangerous-git.sh`** — blocks destructive or hook-bypassing git commands (`git push`, `reset --hard`, `clean -f/-fd`, `branch -D`, `checkout .`, `restore .`, `--force`, `--no-verify`).
- **`file-guard.py`** — blocks `Read`/`Edit`/`Write`/`MultiEdit`/`NotebookEdit`/`Bash` access to secret files (`.env` and friends) and exfiltration patterns. Symlink-aware (can't bypass via `ln -s .env /tmp/x`). Case-insensitive. Fails open on malformed input.

## Per-project whitelist

Drop a file at `.claude/safety-hooks.local.md` in your project root to exempt specific patterns from the dangerous-git hook:

```markdown
---
allow:
  - "git push"
  - "--no-verify"
---

# Notes
This repo allows push because we deploy here daily.
```

- Default behavior is **strict**: if the file is missing, all dangerous patterns are blocked.
- Patterns must match the literal entries in `DANGEROUS_PATTERNS` inside `block-dangerous-git.sh`.
- Whitelist edits take effect immediately (read on every Bash tool call). No restart required.
- Malformed config falls back to blocking — the hook fails closed, so a typo can't accidentally disable safety.

### Whitelist lookup paths

The hook checks two locations in order:

1. **`<cd-target>/.claude/safety-hooks.local.md`** — if the bash command starts with `cd <path> && ...` (Claude Code's common compound pattern), the cd target is used as the lookup root. This is the typical case for working with a project repo from a different CWD.
2. **`$(pwd)/.claude/safety-hooks.local.md`** — fallback when there is no leading `cd`.

This means a project's whitelist file at the repo root works whether the bash command is run from inside the repo or via `cd <repo> && ...` from elsewhere.

This file should typically be **committed**, so the whitelist is auditable in `git diff` and travels with the repo.

`file-guard.py` does not currently honor this whitelist — its escape hatches (`.env.example`, etc.) are hardcoded inside the script.

## Configuration

Edit `block-dangerous-git.sh` to extend the `DANGEROUS_PATTERNS` array.
Edit `file-guard.py` `PROTECTED_PATTERNS` / `ALLOWED_PATTERNS` / `DANGEROUS_BASH_PATTERNS` lists — they are source-of-truth (no separate config file).

## Tests

```bash
cd plugins/safety-hooks
uv run pytest tests/
```

`test_file_guard.py` covers the Python hook. The bash hook is tested via the integration script in the repo CI (or manually via `/tmp/test-safety-hook.sh` during development).

## Install

Via the `Volodyasp/skills` marketplace:

```bash
claude plugin marketplace add Volodyasp/skills
claude plugin install safety-hooks@skills
```

After install, restart Claude Code. Hooks activate automatically (no `~/.claude/settings.json` editing needed).

## Why hooks instead of permission rules

Claude Code permission rules (in `settings.json` `permissions.deny`) are a `tool→pattern` allowlist. They cover most cases but:

- Don't run scripts (no JSON parsing, no symlink resolution, no per-file content inspection).
- Don't support per-project escape hatches without committing changes to user-level settings.
- Don't compose well with audit/logging.

Hooks are full programs. They get the entire tool input, can shell out, and decide based on whatever logic you want. Use permissions for coarse rules, hooks for nuanced safety nets.
