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
- Patterns are matched as **literal substrings** (`grep -F`). No regex — the entries you write are exactly what's compared. Case-sensitive.
- Patterns must match the literal entries in `DANGEROUS_PATTERNS` inside `block-dangerous-git.sh`.
- Whitelist edits take effect immediately (read on every Bash tool call). No restart required.
- Malformed config falls back to blocking — the hook fails closed, so a typo can't accidentally disable safety.

### Pattern overlap

A single command can trigger MULTIPLE entries in `DANGEROUS_PATTERNS` — e.g. `git push --force` matches both `"git push"` and `"push --force"`. To allow such a command you must whitelist **all** patterns it triggers; whitelisting just one isn't enough. Same applies to `git reset --hard` (triggers `"git reset --hard"` and `"reset --hard"`).

This is intentional: defense-in-depth means we'd rather over-block than silently let force-push slip through because the user only listed `"git push"`.

### Whitelist lookup

The hook resolves a starting directory, then **walks UP** to the filesystem root looking for `.claude/safety-hooks.local.md` — same way git itself finds `.git/` from anywhere inside the tree.

Starting directory is chosen in priority order:

1. **`git -C <path> ...`** — explicit git working directory.
2. **`cd <path> && ...`** — Claude Code's common compound pattern when working on a repo from a different CWD.
3. **`$(pwd)`** — fallback.

Walk-up means a single whitelist at the repo root applies whether the command runs from inside the repo, a subdirectory, or via `cd`/`-C` from elsewhere. The deepest matching whitelist wins (a subdirectory can override its parent).

The whitelist file should typically be **committed**, so policy is auditable in `git diff` and travels with the repo.

`file-guard.py` does not currently honor this whitelist — its escape hatches (`.env.example`, etc.) are hardcoded inside the script.

### Known limitations

- **Paths with spaces**: the hook parses `cd <path>` and `git -C <path>` with regex that stops at whitespace. `cd "/path with spaces" && ...` is not parsed as a single token; the whitelist lookup falls back to `$(pwd)`. Workaround: invoke the command from inside the spaced directory rather than via `cd`/`-C`.
- **Inline YAML comments after a pattern**: `- "git push"  # comment` is treated as a literal pattern with the comment included; it won't exempt. Put comments on their own line (outside frontmatter or as a separate `# Notes` section).
- **Malformed payload**: if the Bash tool input is missing `command` or stdin isn't valid JSON, the hook fails closed (exits 2) rather than passing through. Bash tool calls always carry `command`, so this is only an issue with experimental clients.

## Configuration

Edit `block-dangerous-git.sh` to extend the `DANGEROUS_PATTERNS` array.
Edit `file-guard.py` `PROTECTED_PATTERNS` / `ALLOWED_PATTERNS` / `DANGEROUS_BASH_PATTERNS` lists — they are source-of-truth (no separate config file).

## Tests

```bash
cd plugins/safety-hooks
uv run --with pytest python -m pytest tests/ -v
```

- `tests/test_file_guard.py` — covers the Python hook (path matching, symlink resolution, Bash exfil patterns, fail-open behavior).
- `tests/test_block_dangerous_git.py` — covers the bash hook (every dangerous pattern, whitelist exemption, `cd <path>` / `git -C <path>` lookup, walk-up to parent directories, malformed-config fail-closed, malformed-stdin fail-open).

Both hook scripts run as subprocesses with synthetic PreToolUse JSON on stdin, matching the real Claude Code contract.

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
