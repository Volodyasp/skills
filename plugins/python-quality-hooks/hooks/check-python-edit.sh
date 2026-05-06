#!/usr/bin/env bash
# PostToolUse hook for Edit: bugs-only ruff check + mypy on Python files.
# Non-blocking: prints findings to stdout, always exits 0.
# Skips silently if jq / ruff / mypy are not installed.

set -u

command -v jq >/dev/null 2>&1 || exit 0

f=$(jq -r '.tool_input.file_path // empty')
[[ "$f" == *.py && -f "$f" ]] || exit 0

r=""
if command -v ruff >/dev/null 2>&1; then
  r=$(ruff check "$f" --select=F,B,E9,E71,S,ASYNC,DTZ --quiet --no-fix 2>&1) || true
fi

m=""
if command -v mypy >/dev/null 2>&1; then
  m=$(mypy "$f" --ignore-missing-imports --follow-imports=silent --no-error-summary 2>&1 \
    | grep -v '^Success:' || true)
fi

[[ -n "$r" ]] && printf 'ruff (bugs-only):\n%s\n' "$r"
[[ -n "$m" ]] && printf 'mypy:\n%s\n' "$m"

exit 0
