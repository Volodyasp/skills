"""Regression tests for block-dangerous-git.sh.

The hook is exercised as a subprocess with synthetic PreToolUse JSON on
stdin (matching the real Claude Code contract). Tests cover:

- DANGEROUS_PATTERNS — each entry blocks
- Harmless commands — pass through
- Whitelist — exempts specific patterns, only the listed ones
- Lookup priority — `git -C <path>` > leading `cd <path>` > $(pwd)
- Walk-up — whitelist at repo root applies from any subdirectory
- Fail-closed — malformed whitelist YAML reverts to blocking
- Fail-open — malformed JSON stdin does not crash

Tests that touch lookup logic always pass an isolated `cwd=tmp_path` to
prevent the developer's real ~/.claude/safety-hooks.local.md from leaking
into the assertion.
"""

from __future__ import annotations

from pathlib import Path

import pytest

# ---------- Dangerous patterns must block ----------

DANGEROUS_COMMANDS = [
    ("git push", "git push origin main"),
    ("git push --force", "git push --force origin main"),
    ("git reset --hard", "git reset --hard HEAD"),
    ("git clean -f", "git clean -f"),
    ("git clean -fd", "git clean -fd"),
    ("git branch -D", "git branch -D feature-x"),
    ("git checkout .", "git checkout ."),
    ("git restore .", "git restore ."),
    ("--no-verify on commit", "git commit --no-verify -m 'hi'"),
    ("--no-verify on push", "git push --no-verify origin main"),
    ("push --force without space", "git push --force-with-lease origin main"),
]


@pytest.mark.parametrize(
    ("name", "command"), DANGEROUS_COMMANDS, ids=[c[0] for c in DANGEROUS_COMMANDS]
)
def test_dangerous_command_blocked(run_block_git, tmp_path, name, command):
    result = run_block_git(command, cwd=tmp_path)
    assert result.blocked, f"{name!r} should be blocked but exit was {result.exit_code}"
    assert "BLOCKED" in result.stderr


# ---------- Harmless commands must pass ----------

HARMLESS_COMMANDS = [
    "git status",
    "git log --oneline",
    "git diff",
    "git pull",
    "git fetch origin",
    "git add .",
    "git commit -m 'wip'",
    "git checkout main",
    "git checkout -b feature-x",
    "git restore --staged file.py",
    "ls -la",
    "echo 'git push is mentioned in this string but not executed'",  # known false-positive
]


@pytest.mark.parametrize("command", HARMLESS_COMMANDS)
def test_harmless_command_allowed(run_block_git, tmp_path, command):
    # `echo "git push ..."` is a known false-positive: hook treats cmd as a
    # flat string and can't shell-parse. Documented; not asserted here.
    if "git push" in command and not command.startswith("echo"):
        pytest.skip("dangerous content")
    result = run_block_git(command, cwd=tmp_path)
    if "git push" in command:
        # echo case — confirm we acknowledge the known false-positive by
        # asserting the hook DOES block it rather than pretending otherwise.
        assert result.blocked
    else:
        assert result.allowed, f"{command!r} unexpectedly blocked: {result.stderr}"


# ---------- Whitelist exempts listed patterns ----------


def test_whitelist_exempts_listed_pattern(run_block_git, make_whitelist, tmp_path):
    make_whitelist(tmp_path, ["git push"])
    result = run_block_git("git push origin main", cwd=tmp_path)
    assert result.allowed, f"whitelisted 'git push' should pass: {result.stderr}"


def test_whitelist_does_not_exempt_unlisted_pattern(run_block_git, make_whitelist, tmp_path):
    make_whitelist(tmp_path, ["git push"])
    # `--no-verify` is NOT in the whitelist — must still block.
    result = run_block_git("git commit --no-verify -m 'hi'", cwd=tmp_path)
    assert result.blocked


def test_empty_whitelist_blocks_everything(run_block_git, make_whitelist, tmp_path):
    make_whitelist(tmp_path, [])  # frontmatter present, no allow entries
    result = run_block_git("git push origin main", cwd=tmp_path)
    assert result.blocked


def test_missing_whitelist_blocks_everything(run_block_git, tmp_path):
    # No file at all — strict default.
    result = run_block_git("git push origin main", cwd=tmp_path)
    assert result.blocked


# ---------- Lookup: cd-target ----------


def test_cd_target_uses_target_whitelist(run_block_git, make_whitelist, tmp_path):
    """`cd /target && git push` must consult /target/.claude/, not $(pwd)/.claude/."""
    target = tmp_path / "repo"
    target.mkdir()
    make_whitelist(target, ["git push"])

    cwd = tmp_path / "elsewhere"
    cwd.mkdir()

    result = run_block_git(f"cd {target} && git push origin main", cwd=cwd)
    assert result.allowed, f"cd-target whitelist should apply: {result.stderr}"


def test_cd_target_nonexistent_falls_back_to_cwd(run_block_git, make_whitelist, tmp_path):
    cwd = tmp_path / "here"
    cwd.mkdir()
    make_whitelist(cwd, ["git push"])

    # cd target doesn't exist — hook should ignore it and use $(pwd).
    result = run_block_git("cd /nonexistent/totally && git push origin main", cwd=cwd)
    assert result.allowed


# ---------- Lookup: git -C ----------


def test_git_dash_C_uses_target_whitelist(run_block_git, make_whitelist, tmp_path):
    target = tmp_path / "repo"
    target.mkdir()
    make_whitelist(target, ["git push"])

    cwd = tmp_path / "elsewhere"
    cwd.mkdir()

    result = run_block_git(f"git -C {target} push origin main", cwd=cwd)
    assert result.allowed, f"git -C whitelist should apply: {result.stderr}"


def test_git_dash_C_takes_priority_over_cd(run_block_git, make_whitelist, tmp_path):
    """When both `cd <path>` and `git -C <path>` appear, git -C wins."""
    a = tmp_path / "a"
    b = tmp_path / "b"
    a.mkdir()
    b.mkdir()
    # only b has whitelist
    make_whitelist(b, ["git push"])

    # cd to a, but git -C points at b. Whitelist at b should apply.
    result = run_block_git(f"cd {a} && git -C {b} push origin main", cwd=tmp_path)
    assert result.allowed


# ---------- Lookup: walk-up ----------


def test_walk_up_finds_whitelist_at_parent(run_block_git, make_whitelist, tmp_path):
    """Whitelist at <repo>/.claude/ should apply when running from <repo>/sub/dir."""
    make_whitelist(tmp_path, ["git push"])

    deep = tmp_path / "sub" / "dir"
    deep.mkdir(parents=True)

    result = run_block_git("git push origin main", cwd=deep)
    assert result.allowed, f"walk-up should find parent whitelist: {result.stderr}"


def test_walk_up_picks_nearest_whitelist(run_block_git, make_whitelist, tmp_path):
    """Nearest .claude/safety-hooks.local.md (deepest) wins."""
    make_whitelist(tmp_path, [])  # outer: no allows
    inner = tmp_path / "inner"
    inner.mkdir()
    make_whitelist(inner, ["git push"])

    result = run_block_git("git push origin main", cwd=inner)
    assert result.allowed


# ---------- Whitelist file robustness ----------


def test_whitelist_with_unquoted_pattern(run_block_git, tmp_path):
    """YAML allows unquoted strings — hook should strip quotes either way."""
    (tmp_path / ".claude").mkdir()
    (tmp_path / ".claude" / "safety-hooks.local.md").write_text("---\nallow:\n  - git push\n---\n")
    result = run_block_git("git push origin main", cwd=tmp_path)
    assert result.allowed


def test_whitelist_outside_frontmatter_ignored(run_block_git, tmp_path):
    """Bullet items in the markdown body (after frontmatter) must NOT exempt."""
    (tmp_path / ".claude").mkdir()
    (tmp_path / ".claude" / "safety-hooks.local.md").write_text(
        '---\nallow: []\n---\n\n# Notes\n  - "git push"\n'
    )
    result = run_block_git("git push origin main", cwd=tmp_path)
    assert result.blocked


def test_no_frontmatter_blocks_everything(run_block_git, tmp_path):
    """A whitelist file with no `---` frontmatter should be treated as empty."""
    (tmp_path / ".claude").mkdir()
    (tmp_path / ".claude" / "safety-hooks.local.md").write_text(
        '# just notes, no frontmatter\n  - "git push"\n'
    )
    result = run_block_git("git push origin main", cwd=tmp_path)
    assert result.blocked


# ---------- Fail-open on bad input ----------


def test_malformed_json_does_not_crash(tmp_path):
    """Hook should not raise on malformed stdin — fail open or fail closed,
    but not crash with a traceback / nonzero unrelated exit."""
    import subprocess

    proc = subprocess.run(
        ["bash", str(Path(__file__).resolve().parent.parent / "hooks" / "block-dangerous-git.sh")],
        input=b"not json {{",
        capture_output=True,
        timeout=5,
        check=False,
        cwd=str(tmp_path),
    )
    # Allowed exit codes: 0 (fail open) or 2 (fail closed). Anything else
    # means the script crashed.
    assert proc.returncode in (0, 2), (
        f"hook crashed on malformed JSON (exit={proc.returncode}, stderr={proc.stderr!r})"
    )


# ---------- Multi-pattern command interaction ----------
#
# A single command can trigger MULTIPLE dangerous patterns. The whitelist
# logic iterates each matched pattern; ANY unmatched-but-triggered pattern
# blocks. This is intentional: whitelisting "git push" alone shouldn't
# silently green-light "git push --force" (which also triggers "push --force").


def test_multipattern_partial_whitelist_blocks(run_block_git, make_whitelist, tmp_path):
    """`git push && git reset --hard` triggers BOTH patterns. Only `git push`
    is whitelisted, so `git reset --hard` part still blocks the whole command."""
    make_whitelist(tmp_path, ["git push"])
    result = run_block_git("git push origin main && git reset --hard HEAD", cwd=tmp_path)
    assert result.blocked
    # Block reason should name the unwhitelisted pattern, not the whitelisted one.
    assert "reset --hard" in result.stderr or "git reset --hard" in result.stderr


def test_pattern_overlap_force_push_partial_whitelist(run_block_git, make_whitelist, tmp_path):
    """`git push --force` triggers BOTH `git push` AND `push --force` patterns.
    Whitelisting only `git push` is insufficient — `push --force` still blocks."""
    make_whitelist(tmp_path, ["git push"])
    result = run_block_git("git push --force origin main", cwd=tmp_path)
    assert result.blocked
    assert "push --force" in result.stderr


def test_pattern_overlap_force_push_full_whitelist(run_block_git, make_whitelist, tmp_path):
    """Whitelisting BOTH overlapping patterns lets force-push through."""
    make_whitelist(tmp_path, ["git push", "push --force"])
    result = run_block_git("git push --force origin main", cwd=tmp_path)
    assert result.allowed, f"both overlapping patterns whitelisted should allow: {result.stderr}"


def test_reset_hard_overlap_requires_both_patterns(run_block_git, make_whitelist, tmp_path):
    """`git reset --hard` triggers both `git reset --hard` AND `reset --hard`.
    Whitelisting only the first leaves the second to block."""
    make_whitelist(tmp_path, ["git reset --hard"])
    result = run_block_git("git reset --hard HEAD", cwd=tmp_path)
    assert result.blocked


def test_reset_hard_overlap_both_whitelisted(run_block_git, make_whitelist, tmp_path):
    make_whitelist(tmp_path, ["git reset --hard", "reset --hard"])
    result = run_block_git("git reset --hard HEAD", cwd=tmp_path)
    assert result.allowed


def test_chained_safe_then_dangerous_blocks(run_block_git, tmp_path):
    """`git status && git push` — second part is dangerous, must block whole."""
    result = run_block_git("git status && git push origin main", cwd=tmp_path)
    assert result.blocked


# ---------- Whitelist YAML robustness ----------


def test_whitelist_mixed_quote_styles(run_block_git, tmp_path):
    """Awk strips outer single OR double quotes; unquoted entries also work.

    Note: `reset --hard` is also listed because `git reset --hard` triggers
    BOTH the `git reset --hard` and bare `reset --hard` patterns (overlap
    behavior — whitelisting `git reset --hard` alone is insufficient)."""
    (tmp_path / ".claude").mkdir()
    (tmp_path / ".claude" / "safety-hooks.local.md").write_text(
        "---\n"
        "allow:\n"
        '  - "git push"\n'
        "  - 'git reset --hard'\n"
        "  - reset --hard\n"  # unquoted, paired w/ overlap
        "  - --no-verify\n"
        "---\n"
    )
    for cmd in (
        "git push origin main",
        "git reset --hard HEAD",
        "git commit --no-verify -m hi",
    ):
        result = run_block_git(cmd, cwd=tmp_path)
        assert result.allowed, f"{cmd!r} should be allowed: {result.stderr}"


def test_whitelist_with_blank_lines_between_entries(run_block_git, tmp_path):
    """Blank lines inside frontmatter must not break parsing."""
    (tmp_path / ".claude").mkdir()
    (tmp_path / ".claude" / "safety-hooks.local.md").write_text(
        '---\nallow:\n  - "git push"\n\n  - "git reset --hard"\n  - "reset --hard"\n---\n'
    )
    assert run_block_git("git push origin main", cwd=tmp_path).allowed
    assert run_block_git("git reset --hard HEAD", cwd=tmp_path).allowed


def test_whitelist_empty_zero_byte_file(run_block_git, tmp_path):
    """Empty file (no frontmatter at all) → fail-closed (no exemptions)."""
    (tmp_path / ".claude").mkdir()
    (tmp_path / ".claude" / "safety-hooks.local.md").write_text("")
    assert run_block_git("git push origin main", cwd=tmp_path).blocked


def test_whitelist_frontmatter_without_allow_key(run_block_git, tmp_path):
    """Frontmatter present but no `allow:` list → still strict.

    The awk heuristic captures any `- item` line inside `--- ... ---`. This
    is intentionally simple (we're not a YAML parser). Hardening: a future
    `key: value` filter could constrain to entries under `allow:`. For now,
    confirm that bullets ABOVE/AROUND non-allow keys are still parsed —
    test asserts the documented limitation, not future stricter behavior."""
    (tmp_path / ".claude").mkdir()
    (tmp_path / ".claude" / "safety-hooks.local.md").write_text(
        '---\ntitle: My Notes\n---\n- "git push"\n'  # outside frontmatter — must be ignored
    )
    assert run_block_git("git push origin main", cwd=tmp_path).blocked


def test_whitelist_pattern_case_sensitive(run_block_git, tmp_path):
    """Whitelist matching is case-sensitive (grep -F is). `Git Push` ≠ `git push`."""
    (tmp_path / ".claude").mkdir()
    (tmp_path / ".claude" / "safety-hooks.local.md").write_text(
        '---\nallow:\n  - "Git Push"\n---\n'
    )
    assert run_block_git("git push origin main", cwd=tmp_path).blocked


def test_whitelist_pattern_with_trailing_inline_comment(run_block_git, tmp_path):
    """Inline `# comment` after a pattern is treated as part of the value
    (we don't parse YAML comments). Document this as a limitation."""
    (tmp_path / ".claude").mkdir()
    (tmp_path / ".claude" / "safety-hooks.local.md").write_text(
        '---\nallow:\n  - "git push"  # daily deploys\n---\n'
    )
    # The awk extraction takes everything after `-`, then strips outer quotes.
    # Result: `git push"  # daily deploys` (the closing `"` is mid-string).
    # That literal string isn't a DANGEROUS_PATTERN, so no exemption — block.
    # Documents that users SHOULDN'T put inline comments after patterns.
    assert run_block_git("git push origin main", cwd=tmp_path).blocked


def test_whitelist_with_dangerous_pattern_containing_dot(run_block_git, tmp_path):
    """`git checkout .` is in DANGEROUS_PATTERNS as a literal (no regex
    escape since v0.3.0). Whitelist with the literal form must exempt."""
    (tmp_path / ".claude").mkdir()
    (tmp_path / ".claude" / "safety-hooks.local.md").write_text(
        '---\nallow:\n  - "git checkout ."\n  - "git restore ."\n---\n'
    )
    assert run_block_git("git checkout .", cwd=tmp_path).allowed
    assert run_block_git("git restore .", cwd=tmp_path).allowed


# ---------- cd / git -C parsing edge cases ----------


def test_cd_path_with_trailing_slash(run_block_git, make_whitelist, tmp_path):
    """`cd /repo/ && git push` — trailing slash in path mustn't break lookup."""
    repo = tmp_path / "repo"
    repo.mkdir()
    make_whitelist(repo, ["git push"])
    result = run_block_git(f"cd {repo}/ && git push origin main", cwd=tmp_path)
    assert result.allowed


def test_cd_chain_last_target_wins(run_block_git, make_whitelist, tmp_path, tmp_path_factory):
    """`cd a && cd b && git push` — sticky cd semantics: each cd updates
    the effective cwd, so the LAST cd wins (matches real shell behavior).
    Pre-v0.7.0 the hook took the first cd via `head -1`, which was wrong:
    if `a` was a trusted repo and `b` was a malicious one, push ran from
    `b` but the whitelist was looked up at `a`."""
    a = tmp_path_factory.mktemp("a-orphan") / "a"
    a.mkdir(parents=True)
    # `a` has the whitelist as a decoy — if hook still picks first cd,
    # this test would (incorrectly) allow.
    make_whitelist(a, ["git push"])

    b = tmp_path / "b"
    b.mkdir()
    make_whitelist(b, ["git push"])

    result = run_block_git(f"cd {a} && cd {b} && git push origin main", cwd=tmp_path)
    assert result.allowed, (
        f"last-cd-wins broken: push should run from `b` (which is whitelisted). "
        f"stderr={result.stderr!r}"
    )


def test_cd_chain_last_target_blocks_when_only_first_whitelisted(
    run_block_git, make_whitelist, tmp_path, tmp_path_factory
):
    """Mirror of above: when ONLY the first cd target has the whitelist
    (and second is in an isolated tree without whitelist), the new sticky
    semantics correctly blocks because git push runs from the second cd."""
    a = tmp_path / "a"
    a.mkdir()
    make_whitelist(a, ["git push"])  # first cd target — whitelisted

    b_orphan = tmp_path_factory.mktemp("b-orphan")
    b = b_orphan / "b"
    b.mkdir()  # second cd target, NO whitelist anywhere up its tree

    result = run_block_git(f"cd {a} && cd {b} && git push origin main", cwd=tmp_path)
    assert result.blocked, (
        "sticky-cd: last cd should win, git push runs from `b` (no whitelist), "
        f"must block. stderr={result.stderr!r}"
    )


def test_cd_chain_first_nonexistent_picks_up_second(
    run_block_git, make_whitelist, tmp_path, tmp_path_factory
):
    """First cd to a nonexistent dir does NOT change sticky cwd (real-shell
    failure semantics — `cd /nope` exits non-zero, but the hook can't know
    short-circuit will trigger, so it conservatively assumes the second cd
    runs). Second cd is real, becomes sticky cwd. git push runs from there."""
    cwd = tmp_path / "here"
    cwd.mkdir()
    make_whitelist(cwd, ["git push"])  # decoy at cwd

    other = tmp_path_factory.mktemp("other-orphan") / "other"
    other.mkdir()
    make_whitelist(other, ["git push"])  # whitelist at second cd target

    result = run_block_git(
        f"cd /nonexistent && cd {other} && git push origin main",
        cwd=cwd,
    )
    assert result.allowed, (
        f"second cd should become sticky cwd, push runs from there. stderr={result.stderr!r}"
    )


def test_git_dash_C_with_extra_flags_before_subcommand(run_block_git, make_whitelist, tmp_path):
    """`git -C /path --no-pager push` — sed must capture /path even when
    flags appear between `-C <path>` and the subcommand."""
    repo = tmp_path / "repo"
    repo.mkdir()
    make_whitelist(repo, ["git push"])
    result = run_block_git(f"git -C {repo} --no-pager push origin main", cwd=tmp_path)
    assert result.allowed


def test_git_lowercase_c_not_confused_with_dash_C(
    run_block_git, make_whitelist, tmp_path, tmp_path_factory
):
    """`git -c key=value push` — lowercase `-c` is git config, unrelated to
    `-C` (working dir). Discriminating geometry: lowercase-c value is a
    REAL existing directory in an isolated tree without a whitelist. If the
    hook regex mis-matched lowercase `-c`, walk-up from that decoy would
    miss the whitelist and block."""
    make_whitelist(tmp_path, ["git push"])

    decoy_root = tmp_path_factory.mktemp("decoy")
    decoy = decoy_root / "config"
    decoy.mkdir()  # exists, [ -d ] would pass if regex was case-insensitive

    result = run_block_git(f"git -c {decoy} push origin main", cwd=tmp_path)
    assert result.allowed, (
        "regex confused -c with -C: walk-up consulted decoy dir instead of "
        f"$(pwd). stderr={result.stderr!r}"
    )


def test_git_dash_C_relative_path_via_cwd(run_block_git, make_whitelist, tmp_path):
    """`git -C ./repo push` — relative path resolves against the subprocess
    cwd. If `./repo` exists relative to cwd and has a whitelist, exempt."""
    repo = tmp_path / "repo"
    repo.mkdir()
    make_whitelist(repo, ["git push"])
    result = run_block_git("git -C ./repo push origin main", cwd=tmp_path)
    assert result.allowed


# ---------- Walk-up edge cases ----------


def test_walk_up_deep_nesting(run_block_git, make_whitelist, tmp_path):
    """Walk-up should traverse arbitrary depth without missing the root."""
    make_whitelist(tmp_path, ["git push"])
    deep = tmp_path / "a" / "b" / "c" / "d" / "e" / "f"
    deep.mkdir(parents=True)
    assert run_block_git("git push origin main", cwd=deep).allowed


def test_walk_up_does_not_loop_forever_at_root(run_block_git, tmp_path):
    """No whitelist anywhere on the path → walk-up reaches `/` and exits.
    A regression in the loop termination would hang until conftest's 5-second
    subprocess timeout fires (the test would error rather than fail), so a
    quick return + `result.blocked` proves both correctness AND termination."""
    deep = tmp_path / "a" / "b" / "c"
    deep.mkdir(parents=True)
    result = run_block_git("git push origin main", cwd=deep)
    assert result.blocked


def test_walk_up_skips_claude_when_its_a_regular_file(run_block_git, make_whitelist, tmp_path):
    """If `.claude` exists as a plain file (not directory) in some ancestor,
    the file existence check `[ -f .claude/safety-hooks.local.md ]` fails
    cleanly and walk-up continues. Whitelist further up still applies."""
    make_whitelist(tmp_path, ["git push"])
    weird = tmp_path / "weird"
    weird.mkdir()
    (weird / ".claude").write_text("not a directory")  # regular file at .claude
    deep = weird / "deeper"
    deep.mkdir()
    assert run_block_git("git push origin main", cwd=deep).allowed


# ---------- Real-world command shapes ----------


def test_subshell_dangerous_blocks(run_block_git, tmp_path):
    """`(git push origin main)` — hook treats command as flat string,
    parens don't affect substring matching."""
    assert run_block_git("(git push origin main)", cwd=tmp_path).blocked


def test_pipeline_with_dangerous_blocks(run_block_git, tmp_path):
    """`echo foo | git push origin main` — pipeline still contains the
    pattern, must block."""
    assert run_block_git("echo foo | git push origin main", cwd=tmp_path).blocked


def test_line_continuation_dangerous_blocks(run_block_git, tmp_path):
    """`git push \\\n  origin main` — backslash-newline doesn't interrupt
    the substring pattern."""
    assert run_block_git("git push \\\n  origin main", cwd=tmp_path).blocked


def test_command_with_inline_env_var_blocks(run_block_git, tmp_path):
    """`FOO=bar git push origin main` — env-var prefix doesn't shield the
    dangerous subcommand."""
    assert run_block_git("FOO=bar git push origin main", cwd=tmp_path).blocked


def test_long_command_with_trailing_comment(run_block_git, make_whitelist, tmp_path):
    """4000-char trailing string still parses correctly — substring match
    isn't disturbed by command length. Not an argv-limit test (real ARG_MAX
    on macOS/Linux is hundreds of KB); just confirms the hook doesn't
    truncate or choke on long inputs."""
    make_whitelist(tmp_path, ["git push"])
    long_msg = "x" * 4000
    result = run_block_git(f"git push origin main # {long_msg}", cwd=tmp_path)
    assert result.allowed


# ---------- Malformed payload — fail-closed contracts ----------


def test_missing_tool_input_command_blocks(run_file_guard_payload, tmp_path):
    """jq -r prints literal `null` when `.tool_input.command` is absent.
    Hook must fail-closed rather than treating "null" as a benign command
    that matches no patterns."""
    import subprocess

    proc = subprocess.run(
        ["bash", str(Path(__file__).resolve().parent.parent / "hooks" / "block-dangerous-git.sh")],
        input=b'{"tool_name":"Bash","tool_input":{}}',
        capture_output=True,
        timeout=5,
        check=False,
        cwd=str(tmp_path),
    )
    assert proc.returncode == 2, (
        f"missing command must fail-closed, got exit={proc.returncode} stderr={proc.stderr!r}"
    )


def test_empty_command_blocks(tmp_path):
    """Command set to empty string must also fail-closed — same rationale
    as missing key. Empty string can't be inspected for dangerous patterns."""
    import subprocess

    proc = subprocess.run(
        ["bash", str(Path(__file__).resolve().parent.parent / "hooks" / "block-dangerous-git.sh")],
        input=b'{"tool_name":"Bash","tool_input":{"command":""}}',
        capture_output=True,
        timeout=5,
        check=False,
        cwd=str(tmp_path),
    )
    assert proc.returncode == 2


def test_malformed_json_fails_closed(tmp_path):
    """Invalid JSON → jq exits non-zero, captured stdout is empty, the
    empty-COMMAND guard fires → exit 2. v0.3.0 tightened this from
    accept-either-fail-mode to strict fail-closed."""
    import subprocess

    proc = subprocess.run(
        ["bash", str(Path(__file__).resolve().parent.parent / "hooks" / "block-dangerous-git.sh")],
        input=b"not json {{",
        capture_output=True,
        timeout=5,
        check=False,
        cwd=str(tmp_path),
    )
    assert proc.returncode == 2


# ---------- Whitelist parser robustness (CRLF, trailing whitespace, empty bullet) ----------


def test_whitelist_with_crlf_line_endings(run_block_git, tmp_path):
    """Windows-edited whitelists use `\\r\\n`. Awk must strip the trailing
    `\\r` before grep -Fx, otherwise exemption silently fails."""
    (tmp_path / ".claude").mkdir()
    content = '---\r\nallow:\r\n  - "git push"\r\n---\r\n'
    (tmp_path / ".claude" / "safety-hooks.local.md").write_bytes(content.encode())
    assert run_block_git("git push origin main", cwd=tmp_path).allowed


def test_whitelist_with_trailing_whitespace_after_unquoted_value(run_block_git, tmp_path):
    """`  - git push   ` (unquoted, trailing spaces) must still exempt.
    Awk strips trailing whitespace before grep -Fx exact-line comparison."""
    (tmp_path / ".claude").mkdir()
    (tmp_path / ".claude" / "safety-hooks.local.md").write_text(
        "---\nallow:\n  - git push   \n---\n"
    )
    assert run_block_git("git push origin main", cwd=tmp_path).allowed


def test_whitelist_empty_bullet_does_not_universal_exempt(run_block_git, tmp_path):
    """An empty bullet `- ` (no value) must NOT exempt anything. The
    `grep -qFx -x` flag is load-bearing here: with -x, an empty whitelist
    line can only match an empty pattern, so DANGEROUS_PATTERNS (all
    non-empty) stay blocked. If someone removed -x, this would universal-
    exempt every dangerous pattern. Regression guard."""
    (tmp_path / ".claude").mkdir()
    (tmp_path / ".claude" / "safety-hooks.local.md").write_text("---\nallow:\n  - \n---\n")
    assert run_block_git("git push origin main", cwd=tmp_path).blocked
    assert run_block_git("git reset --hard HEAD", cwd=tmp_path).blocked
    assert run_block_git("git commit --no-verify -m hi", cwd=tmp_path).blocked


# ---------- Walk-up correctness with relative path ----------


def test_git_dash_C_relative_path_walk_up_terminates(run_block_git, make_whitelist, tmp_path):
    """`git -C ./repo` resolved to a relative path used to feed `dirname`
    a non-absolute starting point, producing `./repo → . → . → ...` (dirname
    of `.` is `.`). With no whitelist immediately at `./repo`, walk-up looped
    until conftest's 5-second timeout fired. v0.3.0 absolutizes the start
    dir via `(cd target && pwd)`. This test exercises the path that used to
    hang: whitelist is at the PARENT of the relative target, not at the
    target itself."""
    repo = tmp_path / "repo"
    repo.mkdir()
    make_whitelist(tmp_path, ["git push"])  # whitelist at PARENT, not at repo

    result = run_block_git("git -C ./repo push origin main", cwd=tmp_path)
    assert result.allowed, (
        "walk-up from absolutized git -C target should reach parent's "
        f"whitelist. stderr={result.stderr!r}"
    )


# ---------- Global-flag bypass regression (Codex P1.1) ----------
#
# Pre-v0.5.0, the dangerous-pattern check used grep -F with literal
# substring "git push". Commands like `git -C /tmp push origin main`
# don't contain that exact substring (between `git` and `push` are
# global flag tokens), so they bypassed every safety check. v0.5.0
# tokenizes the match for "git X..." patterns: `git`, then any number
# of global option tokens, then the dangerous subcommand.

GLOBAL_FLAG_FORMS = [
    ("bare", "git {sub} origin main"),
    ("dash-C absolute", "git -C /tmp {sub} origin main"),
    ("dash-C relative", "git -C ./repo {sub} origin main"),
    ("--no-pager", "git --no-pager {sub} origin main"),
    ("-c key=value", "git -c user.name=foo {sub} origin main"),
    ("--git-dir=path", "git --git-dir=/foo {sub} origin main"),
    ("--bare", "git --bare {sub} origin main"),
    ("multiple globals", "git --no-pager -C /tmp -c k=v {sub} origin main"),
]


@pytest.mark.parametrize(("name", "form"), GLOBAL_FLAG_FORMS, ids=[f[0] for f in GLOBAL_FLAG_FORMS])
def test_push_blocks_under_global_flags(run_block_git, tmp_path, name, form):
    """`git <global-flags>* push` must block regardless of how `git` is
    invoked. Pre-v0.5.0 these all bypassed because the check was a literal
    substring `"git push"` that requires those two tokens to be adjacent."""
    cmd = form.format(sub="push")
    assert run_block_git(cmd, cwd=tmp_path).blocked, f"{name}: {cmd!r} bypassed the push detector"


def test_reset_hard_blocks_under_global_flags(run_block_git, tmp_path):
    """`git -C /tmp reset --hard HEAD` blocks via the bare `reset --hard`
    fragment pattern even pre-v0.5.0; this test pins that the tokenized
    `git reset --hard` pattern ALSO catches it (defense in depth)."""
    for cmd in (
        "git -C /tmp reset --hard HEAD",
        "git --no-pager reset --hard",
        "git -c x=y reset --hard origin/main",
    ):
        assert run_block_git(cmd, cwd=tmp_path).blocked, f"{cmd!r} bypassed"


def test_checkout_dot_blocks_under_global_flags(run_block_git, tmp_path):
    """`git -C /repo checkout .` — the dot-pattern must catch this too."""
    assert run_block_git("git -C /tmp checkout .", cwd=tmp_path).blocked
    assert run_block_git("git --no-pager checkout .", cwd=tmp_path).blocked


def test_word_boundary_no_false_positives(run_block_git, tmp_path):
    """`git` as a substring of another identifier (e.g. `digit`, `gitaly`)
    must NOT trigger the regex. Same for subcommand-as-substring."""
    # `digital` contains `git` substring but isn't `git` as a word.
    assert run_block_git("digital push origin main", cwd=tmp_path).allowed
    # `gitaly push` — `gitaly` is a different word; must not match.
    assert run_block_git("gitaly push origin main", cwd=tmp_path).allowed
    # `pushd` is not `git push` even with `git` in command — wait, no `git`.
    assert run_block_git("pushd /tmp", cwd=tmp_path).allowed
    # `git pushdir` — fake subcommand "pushdir" — `push` isn't a separate
    # word here. Should NOT match (subcommand boundary).
    assert run_block_git("git pushdir foo", cwd=tmp_path).allowed


def test_dash_C_lookup_with_reset_hard_whitelist(
    run_block_git, make_whitelist, tmp_path, tmp_path_factory
):
    """Codex P2 calibration: `git -C <repo> reset --hard HEAD` with a
    whitelist at <repo>/.claude/ allowing both `git reset --hard` and
    `reset --hard` must be ALLOWED. This proves that:
    1. The sed extracts `<repo>` from `git -C <repo>` (no \\b reliance).
    2. resolve_start_dir absolutizes the path so walk-up reaches the
       whitelist.
    3. The whitelist exempts both overlapping reset patterns."""
    repo = tmp_path / "repo"
    repo.mkdir()
    make_whitelist(repo, ["git reset --hard", "reset --hard"])

    cwd_outside = tmp_path_factory.mktemp("elsewhere")
    result = run_block_git(f"git -C {repo} reset --hard HEAD", cwd=cwd_outside)
    assert result.allowed, (
        f"git -C lookup failed: whitelist at {repo} not consulted. stderr={result.stderr!r}"
    )


# ---------- allow: key binding regression (Codex P1.2) ----------


def test_deny_key_bullets_do_not_exempt(run_block_git, tmp_path):
    """A YAML `deny:` block (or any non-allow key) must NOT have its
    bullets harvested as exemptions. Pre-v0.5.0, the awk parser accepted
    every bullet inside frontmatter, turning unrelated metadata sections
    into accidental safety bypasses."""
    (tmp_path / ".claude").mkdir()
    (tmp_path / ".claude" / "safety-hooks.local.md").write_text('---\ndeny:\n  - "git push"\n---\n')
    assert run_block_git("git push origin main", cwd=tmp_path).blocked


def test_notes_key_bullets_do_not_exempt(run_block_git, tmp_path):
    """Same as above for arbitrary key names — only `allow:` is honored."""
    (tmp_path / ".claude").mkdir()
    (tmp_path / ".claude" / "safety-hooks.local.md").write_text(
        '---\nnotes:\n  - "git push"\ntitle: My Repo\n---\n'
    )
    assert run_block_git("git push origin main", cwd=tmp_path).blocked


def test_allow_then_deny_mixed_keys(run_block_git, tmp_path):
    """`allow: [git push]` then `deny: [--no-verify]` — only allow's
    bullets exempt; deny's are ignored. Validates state transitions
    in the awk parser when keys alternate."""
    (tmp_path / ".claude").mkdir()
    (tmp_path / ".claude" / "safety-hooks.local.md").write_text(
        '---\nallow:\n  - "git push"\ndeny:\n  - "--no-verify"\n---\n'
    )
    assert run_block_git("git push origin main", cwd=tmp_path).allowed
    # --no-verify should still block (deny: doesn't enable, just doesn't exempt)
    assert run_block_git("git commit --no-verify -m hi", cwd=tmp_path).blocked


def test_deny_then_allow_mixed_keys(run_block_git, tmp_path):
    """Reverse order: `deny:` first, then `allow:`. The under_allow flag
    must correctly toggle off then on as YAML keys change."""
    (tmp_path / ".claude").mkdir()
    (tmp_path / ".claude" / "safety-hooks.local.md").write_text(
        '---\ndeny:\n  - "git reset --hard"\nallow:\n  - "git push"\n---\n'
    )
    assert run_block_git("git push origin main", cwd=tmp_path).allowed
    assert run_block_git("git reset --hard HEAD", cwd=tmp_path).blocked


# ---------- Documented limitation: path with spaces ----------


def test_cd_path_with_spaces_is_not_supported(run_block_git, make_whitelist, tmp_path):
    """The sed regex stops at whitespace, so `cd "/path with spaces"`
    captures only `"/path` (with leading quote). `[ -d ]` fails on that,
    falls through to $(pwd). This test pins the limitation: a whitelist
    at the spaced path is NOT consulted; only $(pwd)'s whitelist applies.

    Setup: whitelist exists ONLY at the spaced path. cwd has no whitelist.
    Expected: command blocks (whitelist not found via cd-target lookup)."""
    spaced = tmp_path / "path with spaces"
    spaced.mkdir()
    make_whitelist(spaced, ["git push"])

    cwd = tmp_path / "cwd"
    cwd.mkdir()  # no whitelist here, no whitelist in tmp_path either
    # tmp_path itself has no whitelist created by make_whitelist (we only
    # wrote one in `spaced`), so walk-up from cwd finds nothing.

    result = run_block_git(f'cd "{spaced}" && git push origin main', cwd=cwd)
    assert result.blocked, (
        "spaced-path support would require shell-aware parsing — "
        "unexpected pass means the limitation has been fixed (update test/README)"
    )


# ---------- git clean force-flag variants (Codex round 3 P1.1) ----------
#
# The dangerous part of `git clean` is the FORCE flag — `-f` short, `-fd`,
# `-df`, `-xdf`, `-fxd`, `--force`. v0.5.0 only matched the literal pattern
# strings `git clean -fd` and `git clean -f`, so reordered or extended flag
# bundles bypassed. v0.6.0 detects any `git clean` invocation that carries
# a force flag in any spelling.

CLEAN_DANGEROUS = [
    "git clean -f",
    "git clean -fd",
    "git clean -df",
    "git clean -xdf",
    "git clean -fxd",
    "git clean -fdx",
    "git clean -nqdf",
    "git clean -df .",
    "git clean --force",
    "git clean --force ./",
    "git -C /tmp clean -xdf",
    "git --no-pager clean -fxd",
    "git -c x=y clean -df",
]


@pytest.mark.parametrize("cmd", CLEAN_DANGEROUS)
def test_git_clean_force_variants_blocked(run_block_git, tmp_path, cmd):
    """Every spelling of `git clean` with a force flag must block."""
    assert run_block_git(cmd, cwd=tmp_path).blocked, f"{cmd!r} bypassed clean force detector"


CLEAN_HARMLESS = [
    "git clean -d",  # remove dirs but no force — git refuses without -f
    "git clean -i",  # interactive
    "git clean -n",  # dry run
    "git clean --dry-run",
    "git clean -nd",  # dry-run + dirs, no force
    "git clean --filter=glob",  # filter, no force
    "git clean -e foo",  # exclude pattern, no force
]


@pytest.mark.parametrize("cmd", CLEAN_HARMLESS)
def test_git_clean_without_force_allowed(run_block_git, tmp_path, cmd):
    """`git clean` without the force flag is harmless — git refuses to
    actually remove without `-f`. Hook must not over-block."""
    assert run_block_git(cmd, cwd=tmp_path).allowed, f"{cmd!r} blocked but has no force flag"


# ---------- :/ root pathspec for checkout/restore (Codex round 3 P1) -------
#
# Git treats `.` AND `:/` as "current dir" / "from-repo-root" pathspecs.
# Both discard tracked changes when used as the only target. Pre-v0.6.0
# only `.` was caught.

PATHSPEC_DANGEROUS = [
    "git restore :/",
    "git restore --staged :/",
    "git restore --staged --worktree :/",
    "git checkout :/",
    "git checkout -- :/",
    "git checkout HEAD -- :/",
    "git -C /tmp restore :/",
    "git --no-pager checkout :/",
]


@pytest.mark.parametrize("cmd", PATHSPEC_DANGEROUS)
def test_root_pathspec_blocked(run_block_git, tmp_path, cmd):
    """`:/` (git's root-of-repo magic pathspec) discards the whole tree."""
    assert run_block_git(cmd, cwd=tmp_path).blocked, f"{cmd!r} bypassed pathspec root"


PATHSPEC_HARMLESS = [
    "git restore main",  # specific branch
    "git checkout main",  # specific branch
    "git restore :/path/to/file",  # specific file from repo root
    "git checkout :/specific.txt",  # specific file
    "git restore --staged file.py",  # specific file
    "git checkout HEAD~1 -- file.txt",  # specific file at revision
]


@pytest.mark.parametrize("cmd", PATHSPEC_HARMLESS)
def test_specific_pathspec_allowed(run_block_git, tmp_path, cmd):
    """Specific files (`file.py`, `:/path/to/file`) are NOT root pathspecs.
    Hook must distinguish bare `:/` from `:/file.txt`."""
    assert run_block_git(cmd, cwd=tmp_path).allowed, (
        f"{cmd!r} blocked but targets a specific file, not the whole tree"
    )


# ---------- git branch force-delete equivalents (Codex round 3 P2) ---------
#
# Multiple equivalent spellings of force-delete. `-D` is the canonical form;
# `--delete --force`, `-d --force`, `--force --delete`, `-d -f`, `-Dfoo`
# (glued) all do the same thing.

BRANCH_FORCE_DELETE = [
    "git branch -D foo",
    "git branch -Dfoo",  # glued short form
    "git branch -D some-feature",
    "git branch --delete --force foo",
    "git branch --force --delete foo",
    "git branch -d --force foo",
    "git branch --force -d foo",
    "git branch -d -f foo",
    "git branch -f -d foo",
    "git branch --delete -f foo",
    "git -C /tmp branch -D foo",
    "git --no-pager branch --delete --force foo",
]


@pytest.mark.parametrize("cmd", BRANCH_FORCE_DELETE)
def test_branch_force_delete_blocked(run_block_git, tmp_path, cmd):
    """All equivalent force-delete spellings must block."""
    assert run_block_git(cmd, cwd=tmp_path).blocked, f"{cmd!r} bypassed branch force-delete"


BRANCH_HARMLESS = [
    "git branch foo",  # create branch
    "git branch -d foo",  # regular delete (only allowed if merged)
    "git branch --delete foo",  # same, long form
    "git branch -m old new",  # rename
    "git branch -f foo",  # force-create/move (no -d, not delete)
    "git branch --list",
    "git branch -a",
    "git branch push",  # branch named "push" — not git push
]


@pytest.mark.parametrize("cmd", BRANCH_HARMLESS)
def test_branch_without_force_delete_allowed(run_block_git, tmp_path, cmd):
    """Regular branch ops, including non-force `-d` and create/rename, allowed."""
    assert run_block_git(cmd, cwd=tmp_path).allowed, f"{cmd!r} blocked but is not a force-delete"


# ---------- -C resolver picks up earlier global flags (Codex round 3 P2) ---


def test_dash_C_lookup_after_no_pager_global(
    run_block_git, make_whitelist, tmp_path, tmp_path_factory
):
    """`git --no-pager -C <repo> reset --hard` — `-C` is preceded by another
    global flag. The resolver must still extract <repo> as the start dir
    so the whitelist at <repo>/.claude/ applies."""
    repo = tmp_path / "repo"
    repo.mkdir()
    make_whitelist(repo, ["git reset --hard", "reset --hard"])

    cwd = tmp_path_factory.mktemp("elsewhere")
    result = run_block_git(f"git --no-pager -C {repo} reset --hard HEAD", cwd=cwd)
    assert result.allowed, f"resolver missed -C after --no-pager global. stderr={result.stderr!r}"


def test_dash_C_lookup_after_dash_c_global(
    run_block_git, make_whitelist, tmp_path, tmp_path_factory
):
    """`git -c key=value -C <repo> reset --hard` — same as above but with
    `-c key=value` (which has its own arg) before `-C`."""
    repo = tmp_path / "repo"
    repo.mkdir()
    make_whitelist(repo, ["git reset --hard", "reset --hard"])

    cwd = tmp_path_factory.mktemp("elsewhere")
    result = run_block_git(f"git -c user.name=alice -C {repo} reset --hard", cwd=cwd)
    assert result.allowed, f"resolver missed -C after -c key=value global. stderr={result.stderr!r}"


# ---------- false positives: pathspecs / args named like subcommands -------
#
# Codex round 3 P3: the v0.5.0 flag-group regex used `[^;&|]*` between
# `git` and the dangerous subcommand, so harmless invocations like
# `git status push` (treating `push` as a pathspec/file arg) were
# misclassified as `git push`. v0.6.0 restricts the pre-subcommand
# stretch to actual git global option tokens.

PUSH_AS_ARG_HARMLESS = [
    "git status push",
    "git log push",
    "git diff push",
    "git diff main..push",
    "git show push",
    "git checkout push",  # branch named "push"
    "git branch push",  # create branch named "push"
    "git tag push",
    "git rev-parse push",
    "git -C /tmp status push",
]


@pytest.mark.parametrize("cmd", PUSH_AS_ARG_HARMLESS)
def test_push_as_argument_not_misclassified(run_block_git, tmp_path, cmd):
    """`push` as a non-subcommand argument must NOT trigger the push detector."""
    assert run_block_git(cmd, cwd=tmp_path).allowed, (
        f"{cmd!r} misclassified as git push — flag-group matcher is too loose"
    )


def test_random_token_before_subcommand_not_treated_as_flag(run_block_git, tmp_path):
    """Anything that doesn't start with `-` between `git` and the
    subcommand must NOT count as a global flag. Belt-and-suspenders for
    the strict matcher."""
    # `foo` between git and push isn't a real git form, but if our regex
    # treats it as a global flag, we'd over-block.
    assert run_block_git("git foo push origin main", cwd=tmp_path).allowed


# ---------- Decoy whitelist hijack regressions (Codex round 4 P1) ----------
#
# Pre-v0.7.0 the hook resolved ONE allow-file for the whole Bash payload,
# so `git -C <allowed-repo> status && git push` made the later push
# inherit <allowed-repo>'s whitelist even though the push runs from $(pwd).
# v0.7.0 splits the command on top-level &&/||/;, resolves each segment's
# effective dir independently. Sticky cd updates carry across segments;
# git -C only applies within ITS segment.


def test_decoy_dash_C_does_not_hijack_later_push(
    run_block_git, make_whitelist, tmp_path, tmp_path_factory
):
    """`git -C <allowed-repo> status && git push origin main` — the second
    push has no `git -C` and runs from $(pwd), not <allowed-repo>. The
    whitelist at <allowed-repo> must NOT exempt the push."""
    allowed_repo = tmp_path_factory.mktemp("allowed-orphan") / "allowed-repo"
    allowed_repo.mkdir(parents=True)
    make_whitelist(allowed_repo, ["git push"])

    cwd = tmp_path / "elsewhere"
    cwd.mkdir()  # no whitelist at cwd or its ancestors

    cmd = f"git -C {allowed_repo} status && git push origin main"
    assert run_block_git(cmd, cwd=cwd).blocked, (
        "decoy hijack: -C in earlier segment must not hijack whitelist for later push"
    )


def test_decoy_dash_C_does_not_hijack_clean_force(
    run_block_git, make_whitelist, tmp_path, tmp_path_factory
):
    """Same hijack via `git clean -xdf` — the force-clean runs from $(pwd),
    not the decoy -C target."""
    allowed_repo = tmp_path_factory.mktemp("allowed-orphan2") / "allowed-repo"
    allowed_repo.mkdir(parents=True)
    make_whitelist(allowed_repo, ["git clean -fd", "git clean -f"])

    cwd = tmp_path / "elsewhere2"
    cwd.mkdir()

    cmd = f"git -C {allowed_repo} status && git clean -xdf"
    assert run_block_git(cmd, cwd=cwd).blocked


def test_dash_C_in_same_segment_still_uses_target_whitelist(
    run_block_git, make_whitelist, tmp_path, tmp_path_factory
):
    """Per-segment resolution must NOT regress the legitimate case:
    `git -C <repo> push` (single segment) → whitelist at <repo> still
    applies because -C and push are in the same segment."""
    repo = tmp_path / "repo"
    repo.mkdir()
    make_whitelist(repo, ["git push"])

    cwd = tmp_path_factory.mktemp("elsewhere3")
    assert run_block_git(f"git -C {repo} push origin main", cwd=cwd).allowed


def test_cd_propagates_across_segments(run_block_git, make_whitelist, tmp_path, tmp_path_factory):
    """Sticky cd: `cd /repo && git push` — cd's effect persists to the
    next segment. Whitelist at /repo must apply to the push."""
    repo = tmp_path / "repo"
    repo.mkdir()
    make_whitelist(repo, ["git push"])

    cwd = tmp_path_factory.mktemp("elsewhere4")
    assert run_block_git(f"cd {repo} && git push origin main", cwd=cwd).allowed


def test_decoy_dash_C_with_status_first_then_dangerous_in_dash_C_repo(
    run_block_git, make_whitelist, tmp_path, tmp_path_factory
):
    """Sanity: `git status && git -C <allowed-repo> push` — second segment
    HAS its own -C, so the whitelist at <allowed-repo> DOES apply. This
    differentiates per-segment resolution from "always use $(pwd)"."""
    allowed_repo = tmp_path / "repo"
    allowed_repo.mkdir()
    make_whitelist(allowed_repo, ["git push"])

    cwd = tmp_path_factory.mktemp("elsewhere5")
    cmd = f"git status && git -C {allowed_repo} push origin main"
    assert run_block_git(cmd, cwd=cwd).allowed


def test_segment_split_handles_logical_or(
    run_block_git, make_whitelist, tmp_path, tmp_path_factory
):
    """`||` is also a top-level separator. Decoy: `git -C <allowed> status
    || git push` must block on the push (which runs from $(pwd))."""
    allowed_repo = tmp_path_factory.mktemp("allowed6") / "allowed"
    allowed_repo.mkdir(parents=True)
    make_whitelist(allowed_repo, ["git push"])

    cwd = tmp_path / "elsewhere6"
    cwd.mkdir()

    cmd = f"git -C {allowed_repo} status || git push origin main"
    assert run_block_git(cmd, cwd=cwd).blocked


def test_segment_split_handles_semicolon(run_block_git, make_whitelist, tmp_path, tmp_path_factory):
    """`;` is also a top-level separator. Same hijack pattern as &&."""
    allowed_repo = tmp_path_factory.mktemp("allowed7") / "allowed"
    allowed_repo.mkdir(parents=True)
    make_whitelist(allowed_repo, ["git push"])

    cwd = tmp_path / "elsewhere7"
    cwd.mkdir()

    cmd = f"git -C {allowed_repo} status; git push origin main"
    assert run_block_git(cmd, cwd=cwd).blocked


def test_decoy_dash_C_pipeline_does_not_hijack_push(
    run_block_git, make_whitelist, tmp_path, tmp_path_factory
):
    """`|` separates commands too. A -C on the left side of a pipeline must
    not scope a dangerous git command on the right side."""
    allowed_repo = tmp_path_factory.mktemp("allowed-pipe") / "allowed"
    allowed_repo.mkdir(parents=True)
    make_whitelist(allowed_repo, ["git push"])

    cwd = tmp_path / "pipe-cwd"
    cwd.mkdir()

    cmd = f"git -C {allowed_repo} status | git push origin main"
    assert run_block_git(cmd, cwd=cwd).blocked


def test_decoy_dash_C_background_does_not_hijack_clean(
    run_block_git, make_whitelist, tmp_path, tmp_path_factory
):
    """Single `&` also separates commands. A backgrounded decoy must not
    whitelist the following force-clean."""
    allowed_repo = tmp_path_factory.mktemp("allowed-bg") / "allowed"
    allowed_repo.mkdir(parents=True)
    make_whitelist(allowed_repo, ["git clean -f", "git clean -fd"])

    cwd = tmp_path / "bg-cwd"
    cwd.mkdir()

    cmd = f"git -C {allowed_repo} status & git clean -xdf"
    assert run_block_git(cmd, cwd=cwd).blocked


def test_dash_C_same_pipeline_command_still_uses_target_whitelist(
    run_block_git, make_whitelist, tmp_path, tmp_path_factory
):
    """Splitting on `|` must not break the legitimate case where the
    dangerous command itself carries `git -C`."""
    repo = tmp_path / "pipe-repo"
    repo.mkdir()
    make_whitelist(repo, ["git push"])

    cwd = tmp_path_factory.mktemp("pipe-elsewhere")
    cmd = f"git -C {repo} push origin main | cat"
    assert run_block_git(cmd, cwd=cwd).allowed


def test_subshell_cd_does_not_spoof_later_push(
    run_block_git, make_whitelist, tmp_path, tmp_path_factory
):
    """A `cd` inside `( ... )` has subshell-local semantics. The parser
    cannot model that safely, so it must not keep using the outer whitelist
    for the inner dangerous command."""
    allowed_repo = tmp_path_factory.mktemp("allowed-sub") / "allowed"
    allowed_repo.mkdir(parents=True)
    make_whitelist(allowed_repo, ["git push"])

    outside = tmp_path / "outside-sub"
    outside.mkdir()

    cmd = f"cd {allowed_repo} && (cd {outside}; git push origin main)"
    assert run_block_git(cmd, cwd=tmp_path).blocked


def test_brace_group_cd_does_not_spoof_later_clean(
    run_block_git, make_whitelist, tmp_path, tmp_path_factory
):
    """Brace groups can also contain local-looking cd flows. Treat them as
    untrusted for inherited whitelist purposes."""
    allowed_repo = tmp_path_factory.mktemp("allowed-brace") / "allowed"
    allowed_repo.mkdir(parents=True)
    make_whitelist(allowed_repo, ["git clean -f", "git clean -fd"])

    outside = tmp_path / "outside-brace"
    outside.mkdir()

    cmd = f"cd {allowed_repo} && {{ cd {outside}; git clean -xdf; }}"
    assert run_block_git(cmd, cwd=tmp_path).blocked


def test_sh_c_cd_does_not_spoof_later_push(
    run_block_git, make_whitelist, tmp_path, tmp_path_factory
):
    """Quoted shell snippets are not parsed as real shell. They must fail
    conservative rather than inheriting the caller's whitelisted cwd."""
    allowed_repo = tmp_path_factory.mktemp("allowed-shc") / "allowed"
    allowed_repo.mkdir(parents=True)
    make_whitelist(allowed_repo, ["git push"])

    outside = tmp_path / "outside-shc"
    outside.mkdir()

    cmd = f"cd {allowed_repo} && sh -c 'cd {outside}; git push origin main'"
    assert run_block_git(cmd, cwd=tmp_path).blocked


def test_git_dash_C_inside_config_value_does_not_hijack_lookup(
    run_block_git, make_whitelist, tmp_path, tmp_path_factory
):
    """A quoted config/alias value may contain the text `git -C <path>`.
    That must not scope the surrounding git invocation."""
    allowed_repo = tmp_path_factory.mktemp("allowed-config") / "allowed"
    allowed_repo.mkdir(parents=True)
    make_whitelist(allowed_repo, ["git push"])

    cwd = tmp_path / "config-cwd"
    cwd.mkdir()

    cmd = f"git -c alias.x='!git -C {allowed_repo} status' push origin main"
    assert run_block_git(cmd, cwd=cwd).blocked


# ---------- ./file overblock regressions (Codex round 4 P2) ----------------
#
# Pre-v0.7.0, the root-pathspec matcher used `[[:space:]/]|$` as the
# end-anchor for `.`, which treated `.` followed by `/` as the whole-tree
# form. This blocked `git restore ./file.py`, `git checkout -- ./foo.py`,
# etc. v0.7.0 distinguishes bare `.` or `./` (whitespace/EOL after) from
# `./file` (more chars after).

DOT_FILE_HARMLESS = [
    "git restore ./file.py",
    "git restore ./src/foo.py",
    "git restore ./path/to/file",
    "git checkout -- ./file.py",
    "git checkout -- ./path/to/file",
    "git restore --staged ./file.py",
    "git restore --staged --worktree ./file.py",
    "git checkout HEAD~1 -- ./file.py",
    "git -C /tmp restore ./file.py",
]


@pytest.mark.parametrize("cmd", DOT_FILE_HARMLESS)
def test_dot_file_pathspec_allowed(run_block_git, tmp_path, cmd):
    """`./file.py` is a specific file, not the whole tree. Hook must allow."""
    assert run_block_git(cmd, cwd=tmp_path).allowed, (
        f"{cmd!r} blocked but targets a specific file, not the whole tree"
    )


DOT_BARE_DANGEROUS = [
    "git restore .",
    "git restore ./",  # trailing slash, still bare-dir form
    "git restore ./ ",  # with trailing whitespace
    "git checkout .",
    "git checkout ./",
    "git checkout -- .",
    "git checkout -- ./",
    "git restore --staged .",
    "git -C /tmp restore .",
    "git -C /tmp checkout ./",
]


@pytest.mark.parametrize("cmd", DOT_BARE_DANGEROUS)
def test_dot_bare_pathspec_still_blocked(run_block_git, tmp_path, cmd):
    """Bare `.` or `./` still discards the whole tree — must block."""
    assert run_block_git(cmd, cwd=tmp_path).blocked, f"{cmd!r} should block as whole-tree pathspec"


# ---------- cd-via-pipe / cd-via-background hijack (Codex round 5 P1) ------
#
# Pre-v0.8.0, splitting on `|` and `&` produced segments but propagated the
# sticky cwd unconditionally across every separator. So a payload like
# `cd /allowed | git push` updated SHELL_CWD to /allowed in segment 1 and
# the next segment's `git push` inherited /allowed's whitelist — even
# though in real shell the cd runs in a pipeline subshell and never
# touches the parent's cwd. v0.8.0 tracks the separator preceding each
# segment and rolls SHELL_CWD back to its pre-previous-segment value
# whenever the separator was `|` or `&`.


def test_cd_pipe_decoy_does_not_hijack_push(
    run_block_git, make_whitelist, tmp_path, tmp_path_factory
):
    """`cd /allowed | git push` runs the cd in a pipeline subshell. The cd
    never updates the parent's cwd, so `git push` must not inherit
    /allowed's whitelist."""
    allowed_repo = tmp_path_factory.mktemp("allowed-cd-pipe") / "allowed"
    allowed_repo.mkdir(parents=True)
    make_whitelist(allowed_repo, ["git push"])

    cwd = tmp_path / "cd-pipe-cwd"
    cwd.mkdir()

    cmd = f"cd {allowed_repo} | git push origin main"
    assert run_block_git(cmd, cwd=cwd).blocked


def test_cd_background_decoy_does_not_hijack_push(
    run_block_git, make_whitelist, tmp_path, tmp_path_factory
):
    """`cd /allowed & git push` backgrounds the cd in a subshell. The
    parent's cwd is unchanged, so `git push` must not inherit /allowed's
    whitelist."""
    allowed_repo = tmp_path_factory.mktemp("allowed-cd-bg") / "allowed"
    allowed_repo.mkdir(parents=True)
    make_whitelist(allowed_repo, ["git push"])

    cwd = tmp_path / "cd-bg-cwd"
    cwd.mkdir()

    cmd = f"cd {allowed_repo} & git push origin main"
    assert run_block_git(cmd, cwd=cwd).blocked


def test_cd_background_decoy_does_not_hijack_clean_force(
    run_block_git, make_whitelist, tmp_path, tmp_path_factory
):
    """Same as above for `git clean -xdf` — the bundled-flag force form."""
    allowed_repo = tmp_path_factory.mktemp("allowed-cd-bg-clean") / "allowed"
    allowed_repo.mkdir(parents=True)
    make_whitelist(allowed_repo, ["git clean -f", "git clean -fd"])

    cwd = tmp_path / "cd-bg-clean-cwd"
    cwd.mkdir()

    cmd = f"cd {allowed_repo} & git clean -xdf"
    assert run_block_git(cmd, cwd=cwd).blocked


def test_pipeline_rhs_cd_does_not_hijack_later_push(
    run_block_git, make_whitelist, tmp_path, tmp_path_factory
):
    """`echo ok | cd /allowed; git push` runs the cd on the right side of a
    pipeline. That cd is still subshell-local and must not affect the later
    semicolon-separated push."""
    allowed_repo = tmp_path_factory.mktemp("allowed-rhs-pipe") / "allowed"
    allowed_repo.mkdir(parents=True)
    make_whitelist(allowed_repo, ["git push"])

    cwd = tmp_path / "rhs-pipe-cwd"
    cwd.mkdir()

    cmd = f"echo ok | cd {allowed_repo}; git push origin main"
    assert run_block_git(cmd, cwd=cwd).blocked


def test_pipeline_rhs_cd_does_not_hijack_later_logical_and_push(
    run_block_git, make_whitelist, tmp_path, tmp_path_factory
):
    """Same pipeline-RHS leak, but followed by `&&` instead of `;`."""
    allowed_repo = tmp_path_factory.mktemp("allowed-rhs-pipe-and") / "allowed"
    allowed_repo.mkdir(parents=True)
    make_whitelist(allowed_repo, ["git push"])

    cwd = tmp_path / "rhs-pipe-and-cwd"
    cwd.mkdir()

    cmd = f"echo ok | cd {allowed_repo} && git push origin main"
    assert run_block_git(cmd, cwd=cwd).blocked


def test_cd_then_pipeline_dangerous_still_uses_cd_target(
    run_block_git, make_whitelist, tmp_path, tmp_path_factory
):
    """`cd /allowed && git push | tee log` — the cd is on the LEFT of `&&`
    (propagating), so the subsequent pipeline inherits /allowed as parent
    cwd. The pipeline subshell starts there, and the dangerous `git push`
    must still be allowed."""
    repo = tmp_path / "cd-then-pipe-repo"
    repo.mkdir()
    make_whitelist(repo, ["git push"])

    cwd = tmp_path_factory.mktemp("cd-then-pipe-elsewhere")
    cmd = f"cd {repo} && git push origin main | tee /tmp/x.log"
    assert run_block_git(cmd, cwd=cwd).allowed


def test_pipeline_then_cd_does_not_save_dangerous(run_block_git, tmp_path):
    """`git push & cd /tmp` — the cd is AFTER the dangerous command. The
    `&` separator means the dangerous push runs in a backgrounded
    subshell from $(pwd), not from /tmp. Cwd has no whitelist → block."""
    cmd = "git push origin main & cd /tmp"
    assert run_block_git(cmd, cwd=tmp_path).blocked


# ---------- invalid cd must not update sticky cwd (Codex round 6 P1) ---------


def test_cd_with_extra_arg_does_not_hijack_later_push(
    run_block_git, make_whitelist, tmp_path, tmp_path_factory
):
    """`cd /allowed extra` fails in Bash with too many arguments. The hook
    must not treat the first path as a successful cwd change."""
    allowed_repo = tmp_path_factory.mktemp("allowed-cd-extra") / "allowed"
    allowed_repo.mkdir(parents=True)
    make_whitelist(allowed_repo, ["git push"])

    cwd = tmp_path / "cd-extra-cwd"
    cwd.mkdir()

    cmd = f"cd {allowed_repo} extra; git push origin main"
    assert run_block_git(cmd, cwd=cwd).blocked


def test_cd_with_extra_arg_before_logical_or_does_not_hijack_push(
    run_block_git, make_whitelist, tmp_path, tmp_path_factory
):
    """With `||`, the failed cd makes the push run from the original cwd."""
    allowed_repo = tmp_path_factory.mktemp("allowed-cd-extra-or") / "allowed"
    allowed_repo.mkdir(parents=True)
    make_whitelist(allowed_repo, ["git push"])

    cwd = tmp_path / "cd-extra-or-cwd"
    cwd.mkdir()

    cmd = f"cd {allowed_repo} extra || git push origin main"
    assert run_block_git(cmd, cwd=cwd).blocked


# ---------- quoted -c value masking later -C (Codex round 5 P3) ------------
#
# Pre-v0.8.0, `_segment_dash_C_target` truncated the segment at the first
# quote. That hid a legitimate later `-C /repo` from view (e.g.
# `git -c alias.x='foo' -C /repo push`), so the hook fell back to $(pwd)
# and overblocked. v0.8.0 collapses each quoted region to a `Q`
# placeholder instead of truncating: the surrounding tokens — including
# any real -C — remain visible, while a `-C /trusted` *inside* a quoted
# value stays hidden because it disappears with its enclosing quotes.


def test_quoted_dash_c_value_does_not_mask_real_dash_C(
    run_block_git, make_whitelist, tmp_path, tmp_path_factory
):
    """A quoted `-c alias.x='foo'` config value precedes a legitimate
    `-C /repo`. The real -C must still scope whitelist lookup."""
    repo = tmp_path / "real-dash-C-repo"
    repo.mkdir()
    make_whitelist(repo, ["git push"])

    cwd = tmp_path_factory.mktemp("dash-c-quote-elsewhere")
    cmd = f"git -c alias.x='foo' -C {repo} push origin main"
    assert run_block_git(cmd, cwd=cwd).allowed


def test_double_quoted_dash_c_value_does_not_mask_real_dash_C(
    run_block_git, make_whitelist, tmp_path, tmp_path_factory
):
    """Same with double-quoted config value."""
    repo = tmp_path / "real-dash-C-repo-dq"
    repo.mkdir()
    make_whitelist(repo, ["git push"])

    cwd = tmp_path_factory.mktemp("dash-c-dq-elsewhere")
    cmd = f'git -c alias.x="foo bar" -C {repo} push origin main'
    assert run_block_git(cmd, cwd=cwd).allowed


def test_quoted_dash_C_inside_value_still_does_not_scope_whitelist(
    run_block_git, make_whitelist, tmp_path, tmp_path_factory
):
    """Inverse invariant: a `-C /trusted` *inside* a quoted alias value
    must NOT count as a real working-dir override. v0.7.0 already had a
    test for this; v0.8.0's quote-replacement fix must preserve it."""
    allowed_repo = tmp_path_factory.mktemp("alias-inner-allowed") / "allowed"
    allowed_repo.mkdir(parents=True)
    make_whitelist(allowed_repo, ["git push"])

    cwd = tmp_path / "alias-inner-cwd"
    cwd.mkdir()

    cmd = f"git -c alias.x='!git -C {allowed_repo} status' push origin main"
    assert run_block_git(cmd, cwd=cwd).blocked
