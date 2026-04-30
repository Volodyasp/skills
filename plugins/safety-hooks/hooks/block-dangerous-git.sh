#!/bin/bash
# block-dangerous-git — PreToolUse hook for Bash commands.
#
# Blocks destructive / hook-bypassing git commands unless the matching pattern
# is listed under `allow:` in the nearest .claude/safety-hooks.local.md.
#
# Whitelist lookup starts from each segment's effective working directory:
#   1. git -C <path>
#   2. a prior simple cd <path> whose effect reaches this shell
#   3. $(pwd)
# Then it walks upward, so a repo-root whitelist applies from subdirectories.

INPUT=$(cat)
COMMAND=$(echo "$INPUT" | jq -r '.tool_input.command')

# Missing or malformed commands cannot be inspected safely.
if [ -z "$COMMAND" ] || [ "$COMMAND" = "null" ]; then
  echo "BLOCKED: safety-hooks received a Bash tool_input without a 'command' field. Refusing to allow the call." >&2
  exit 2
fi

DANGEROUS_PATTERNS=(
  "git push"
  "git reset --hard"
  "git clean -fd"
  "git clean -f"
  "git branch -D"
  "git checkout ."
  "git restore ."
  "push --force"
  "reset --hard"
  "--no-verify"
)

# --- Effective cwd helpers -------------------------------------------------

# Absolute target for a simple `cd <path>` segment. Extra args are rejected
# because Bash would fail the cd instead of changing directory.
_segment_cd_target() {
  local seg="$1"
  local target
  target=$(printf '%s' "$seg" | sed -nE 's|^[[:space:]]*cd[[:space:]]+([^[:space:];&|]+)[[:space:]]*$|\1|p' | head -1)
  [ -n "$target" ] || return 1
  target="${target/#\~/$HOME}"
  local abs
  abs=$(cd "$target" 2>/dev/null && pwd) || return 1
  [ -n "$abs" ] || return 1
  printf '%s' "$abs"
}

# Absolute target for `git ... -C <path>` in this segment.
_segment_dash_C_target() {
  local seg="$1"
  # Hide quoted values so alias/config text cannot spoof a real `-C`.
  seg=$(printf '%s' "$seg" | sed -E "s/'[^']*'/Q/g; s/\"[^\"]*\"/Q/g; s/\`[^\`]*\`/Q/g")
  local target
  target=$(printf '%s' "$seg" | sed -nE 's|.*git[[:space:]]+([^;&|]*[[:space:]])?-C[[:space:]]+([^[:space:];&|]+).*|\2|p' | head -1)
  [ -n "$target" ] || return 1
  target="${target/#\~/$HOME}"
  local abs
  abs=$(cd "$target" 2>/dev/null && pwd) || return 1
  [ -n "$abs" ] || return 1
  printf '%s' "$abs"
}

# Mark inherited cwd untrusted when a segment uses shell constructs this
# lightweight parser cannot model. Same-segment `git -C` remains explicit.
_segment_poison_cwd() {
  local seg="$1"
  case "$seg" in
    *'('*|*')'*|*'{'*|*'}'*|*'$('*|*'`'*)
      return 0
      ;;
  esac
  # Non-simple cd forms may have local/grouped semantics we cannot track.
  if printf '%s' "$seg" | grep -qE -e '(^|[^[:alnum:]_])cd[[:space:]]+'; then
    printf '%s' "$seg" | grep -qE -e '^[[:space:]]*cd[[:space:]]+' && return 1
    return 0
  fi
  return 1
}

# First .claude/safety-hooks.local.md found while walking from $1 to /.
find_allow_file() {
  local dir="$1"
  while [ -n "$dir" ] && [ "$dir" != "/" ]; do
    if [ -f "$dir/.claude/safety-hooks.local.md" ]; then
      printf '%s\n' "$dir/.claude/safety-hooks.local.md"
      return
    fi
    dir=$(dirname "$dir")
  done
  if [ -f "/.claude/safety-hooks.local.md" ]; then
    printf '%s\n' "/.claude/safety-hooks.local.md"
  fi
}

# True when a specific allow-file exempts a dangerous pattern.
allowed_in_file() {
  local pattern="$1"
  local allow_file="$2"
  [ -n "$allow_file" ] && [ -f "$allow_file" ] || return 1
  # Only bullets under the frontmatter `allow:` key count.
  awk '
    BEGIN { fm = 0; under_allow = 0 }
    /^---[[:space:]]*$/ { fm = !fm; under_allow = 0; next }
    !fm { next }
    /^[[:space:]]*$/ { next }
    /^[[:space:]]*#/ { next }
    /^[[:space:]]*allow[[:space:]]*:[[:space:]]*$/ { under_allow = 1; next }
    /^[a-zA-Z][a-zA-Z0-9_-]*[[:space:]]*:/ { under_allow = 0; next }
    under_allow && /^[[:space:]]*-[[:space:]]/ {
      gsub(/^[[:space:]]*-[[:space:]]*/, "")
      sub(/\r$/, "")
      gsub(/[[:space:]]+$/, "")
      gsub(/^"/, ""); gsub(/"$/, "")
      gsub(/^'\''/, ""); gsub(/'\''$/, "")
      print
    }
  ' "$allow_file" | grep -qFx -- "$pattern"
}

# --- Command matching ------------------------------------------------------

# Global git options before the subcommand. Non-flag tokens stop the prefix so
# `git status push` is not treated as `git push`.
GIT_FLAG_TOKEN='-{1,2}[A-Za-z][^[:space:];&|]*'
GIT_FLAG_ARG='[[:space:]]+[^-[:space:];&|][^[:space:];&|]*'
GIT_FLAGS="(${GIT_FLAG_TOKEN}(${GIT_FLAG_ARG})?[[:space:]]+)*"
GIT_PREFIX="(^|[^[:alnum:]_])git[[:space:]]+${GIT_FLAGS}"

# Regex for `git [globals]* <dangerous words...>`.
git_pattern_regex() {
  local pattern="$1"
  local rest="${pattern#git }"
  local escaped="${rest//./\\.}"
  local -a words=()
  read -r -a words <<< "$escaped"
  local regex="${GIT_PREFIX}${words[0]}"
  local i
  for ((i = 1; i < ${#words[@]}; i++)); do
    regex+='[^;&|]*[[:space:]]'"${words[i]}"
  done
  local last="${words[${#words[@]} - 1]}"
  if [[ "$last" =~ [[:alnum:]_]$ ]]; then
    regex+='([^[:alnum:]_]|$)'
  fi
  printf '%s' "$regex"
}

# Collapse quoted strings into shell-token placeholders for matching.
quote_compact() {
  printf '%s' "$1" | sed -E "s/'[^']*'/Q/g; s/\"[^\"]*\"/Q/g"
}

# `git clean` is destructive only when any force spelling is present.
_matches_git_clean_force() {
  local cmd="$1"
  printf '%s' "$cmd" | grep -qE -e "${GIT_PREFIX}clean([[:space:]]|\$)" || return 1
  printf '%s' "$cmd" | grep -qE -e "[[:space:]]-[A-Za-z]*f[A-Za-z]*([^A-Za-z0-9_]|\$)|[[:space:]]--force([^A-Za-z0-9_]|\$)"
}

# `git branch` force-delete equivalents.
_matches_git_branch_force_delete() {
  local cmd="$1"
  printf '%s' "$cmd" | grep -qE -e "${GIT_PREFIX}branch([[:space:]]|\$)" || return 1
  if printf '%s' "$cmd" | grep -qE -e "[[:space:]]-D"; then
    return 0
  fi
  if printf '%s' "$cmd" | grep -qE -e "[[:space:]](-d|--delete)([[:space:]]|\$)" \
    && printf '%s' "$cmd" | grep -qE -e "[[:space:]](-f|--force)([[:space:]]|\$)"; then
    return 0
  fi
  return 1
}

# Whole-tree checkout/restore pathspecs. Specific files are allowed.
_matches_git_pathspec_root() {
  local pattern="$1" cmd="$2"
  local subcmd="${pattern#git }"
  subcmd="${subcmd% .}"  # `checkout .` -> `checkout`, `restore .` -> `restore`
  printf '%s' "$cmd" | grep -qE -e "${GIT_PREFIX}${subcmd}[^;&|]*[[:space:]](\\.[/]?|:/)([[:space:]]|\$)"
}

matches_command() {
  local pattern="$1"
  local cmd="$2"
  case "$pattern" in
    "git clean -f" | "git clean -fd")
      _matches_git_clean_force "$cmd"
      ;;
    "git branch -D")
      _matches_git_branch_force_delete "$cmd"
      ;;
    "git checkout ." | "git restore .")
      _matches_git_pathspec_root "$pattern" "$cmd"
      ;;
    "git "*)
      local regex
      regex=$(git_pattern_regex "$pattern")
      printf '%s' "$cmd" | grep -qE -e "$regex" || quote_compact "$cmd" | grep -qE -e "$regex"
      ;;
    *)
      printf '%s' "$cmd" | grep -qF -- "$pattern"
      ;;
  esac
}

# --- Main loop -------------------------------------------------------------
#
# Separator classes:
#   F first segment
#   P propagating: && || ; newline
#   I pipe: both sides are pipeline members
#   B background: left side is backgrounded, right side stays in parent
#
# The split is intentionally lightweight and may split inside quotes; false
# splits over-block rather than under-block.
PARSED=$(printf '%s' "$COMMAND" | awk '
  BEGIN { sep = "F"; cur = "" }
  { all = all (NR > 1 ? "\n" : "") $0 }
  END {
    n = length(all); i = 1
    while (i <= n) {
      c1 = substr(all, i, 1)
      c2 = substr(all, i, 2)
      if (c2 == "&&" || c2 == "||") {
        print sep "\t" cur; sep = "P"; cur = ""; i += 2
      } else if (c1 == ";" || c1 == "\n") {
        print sep "\t" cur; sep = "P"; cur = ""; i += 1
      } else if (c1 == "|") {
        print sep "\t" cur; sep = "I"; cur = ""; i += 1
      } else if (c1 == "&") {
        print sep "\t" cur; sep = "B"; cur = ""; i += 1
      } else {
        cur = cur c1; i += 1
      }
    }
    print sep "\t" cur
  }
')

SEGMENTS=()
SEPS=()
while IFS=$'\t' read -r _sep _seg; do
  SEGMENTS+=("$_seg")
  SEPS+=("$_sep")
done <<< "$PARSED"

ORIG_CWD=$(pwd)
SHELL_CWD="$ORIG_CWD"
SHELL_CWD_TRUSTED=1
PREV_PRE_CWD="$ORIG_CWD"
PREV_PRE_TRUSTED=1

for i in "${!SEGMENTS[@]}"; do
  seg="${SEGMENTS[$i]}"
  sep="${SEPS[$i]}"
  next_sep=""
  if [ "$((i + 1))" -lt "${#SEGMENTS[@]}" ]; then
    next_sep="${SEPS[$((i + 1))]}"
  fi

  # Previous segment did not propagate cwd into the parent shell.
  if [ "$sep" = "I" ] || [ "$sep" = "B" ]; then
    SHELL_CWD="$PREV_PRE_CWD"
    SHELL_CWD_TRUSTED="$PREV_PRE_TRUSTED"
  fi

  # Rollback target for pipeline/background-local cwd changes.
  pre_cwd="$SHELL_CWD"
  pre_trusted="$SHELL_CWD_TRUSTED"

  seg_trim=$(printf '%s' "$seg" | sed -E 's/^[[:space:]]+//; s/[[:space:]]+$//')
  if [ -z "$seg_trim" ]; then
    PREV_PRE_CWD="$pre_cwd"
    PREV_PRE_TRUSTED="$pre_trusted"
    continue
  fi

  if _segment_poison_cwd "$seg_trim"; then
    SHELL_CWD_TRUSTED=0
  fi

  if _new_cwd=$(_segment_cd_target "$seg_trim"); then
    SHELL_CWD="$_new_cwd"
    SHELL_CWD_TRUSTED=1
  fi

  # `git -C` wins within its own segment; otherwise use trusted sticky cwd.
  if seg_dir=$(_segment_dash_C_target "$seg_trim"); then
    seg_allow=$(find_allow_file "$seg_dir")
  elif [ "$SHELL_CWD_TRUSTED" = "1" ]; then
    seg_allow=$(find_allow_file "$SHELL_CWD")
  else
    seg_allow=""
  fi

  for pattern in "${DANGEROUS_PATTERNS[@]}"; do
    if matches_command "$pattern" "$seg_trim"; then
      if allowed_in_file "$pattern" "$seg_allow"; then
        continue
      fi
      echo "BLOCKED: '$COMMAND' matches dangerous pattern '$pattern'. The user has prevented you from doing this. To allow this pattern in this repo, add it to .claude/safety-hooks.local.md under 'allow:'." >&2
      exit 2
    fi
  done

  # This segment's cwd change is local to a pipeline member or background job.
  if [ "$sep" = "I" ] || [ "$next_sep" = "I" ] || [ "$next_sep" = "B" ]; then
    SHELL_CWD="$pre_cwd"
    SHELL_CWD_TRUSTED="$pre_trusted"
  fi

  PREV_PRE_CWD="$pre_cwd"
  PREV_PRE_TRUSTED="$pre_trusted"
done

exit 0
