#!/bin/bash
# block-dangerous-git — PreToolUse hook on Bash.
#
# Blocks destructive / hook-bypassing git commands. Per-project whitelist via
# .claude/safety-hooks.local.md (YAML frontmatter, "allow" key with list of
# patterns to exempt). Read by every Bash tool call so whitelist edits take
# effect immediately, no restart needed.

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

# Read allow list from .claude/safety-hooks.local.md frontmatter, if it exists.
# Format:
# ---
# allow:
#   - "git push"
#   - "--no-verify"
# ---
# Anything outside the frontmatter (markdown notes) is ignored.
ALLOW_FILE=".claude/safety-hooks.local.md"
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
