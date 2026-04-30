#!/bin/bash
# block-dangerous-git — PreToolUse hook on Bash.
#
# Blocks destructive / hook-bypassing git commands. Per-project whitelist via
# .claude/safety-hooks.local.md (YAML frontmatter, "allow" key with list of
# patterns to exempt). Read on every Bash tool call so whitelist edits take
# effect immediately, no restart needed.
#
# Whitelist lookup walks two locations in order:
#   1. If the command starts with `cd <path> && ...` (the common Claude Code
#      compound pattern), use <path>/.claude/safety-hooks.local.md.
#   2. Otherwise, $(pwd)/.claude/safety-hooks.local.md.
# This handles the typical case where a project repo lives outside CWD but
# the user wants exceptions scoped to that repo.

INPUT=$(cat)
COMMAND=$(echo "$INPUT" | jq -r '.tool_input.command')

DANGEROUS_PATTERNS=(
  "git push"
  "git reset --hard"
  "git clean -fd"
  "git clean -f"
  "git branch -D"
  "git checkout \."
  "git restore \."
  "push --force"
  "reset --hard"
  "--no-verify"
)

# Determine working dir for whitelist lookup. Default to CWD; if the command
# leads with `cd <path>` (followed by &&, ;, or end-of-line), prefer that path.
WORK_DIR="$(pwd)"
CD_TARGET=$(echo "$COMMAND" | sed -nE 's|^[[:space:]]*cd[[:space:]]+([^[:space:];&|]+).*|\1|p' | head -1)
if [ -n "$CD_TARGET" ]; then
  CD_TARGET="${CD_TARGET/#\~/$HOME}"
  if [ -d "$CD_TARGET" ]; then
    WORK_DIR="$CD_TARGET"
  fi
fi
ALLOW_FILE="$WORK_DIR/.claude/safety-hooks.local.md"

allowed_pattern() {
  local pattern="$1"
  [ -f "$ALLOW_FILE" ] || return 1
  awk '
    /^---[[:space:]]*$/ { fm = !fm; next }
    fm && /^[[:space:]]*-[[:space:]]*/ {
      gsub(/^[[:space:]]*-[[:space:]]*/, "")
      gsub(/^"/, ""); gsub(/"$/, "")
      gsub(/^'\''/, ""); gsub(/'\''$/, "")
      print
    }
  ' "$ALLOW_FILE" | grep -qFx -- "$pattern"
}

for pattern in "${DANGEROUS_PATTERNS[@]}"; do
  if echo "$COMMAND" | grep -qE -e "$pattern"; then
    if allowed_pattern "$pattern"; then
      continue
    fi
    echo "BLOCKED: '$COMMAND' matches dangerous pattern '$pattern'. The user has prevented you from doing this. To allow this pattern in this repo, add it to .claude/safety-hooks.local.md under 'allow:'." >&2
    exit 2
  fi
done

exit 0
