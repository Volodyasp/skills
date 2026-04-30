"""Shared fixtures for hook tests.

Run from the hooks/ directory:
    uv run --with pytest python -m pytest tests/ -v

Tests invoke the hook scripts as subprocesses with synthetic PreToolUse
JSON on stdin. This matches the real Claude Code contract (stdin → exit
code + stderr) so a passing test means the hook will behave the same way
when the harness runs it.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

import pytest

HOOKS_DIR = Path(__file__).resolve().parent.parent / "hooks"
FILE_GUARD = HOOKS_DIR / "file-guard.py"
BLOCK_GIT = HOOKS_DIR / "block-dangerous-git.sh"


@dataclass(frozen=True)
class HookResult:
    exit_code: int
    stderr: str

    @property
    def allowed(self) -> bool:
        return self.exit_code == 0

    @property
    def blocked(self) -> bool:
        return self.exit_code == 2


def _run(script: Path, stdin: str | bytes) -> HookResult:
    """Invoke a hook subprocess with arbitrary stdin and capture (exit, stderr).

    Crashes (exit code other than 0 or 2) raise AssertionError immediately
    so a regression that turns a hook into a Python exception isn't
    misreported as "expected block, got allow" by downstream assertions.
    """
    proc = subprocess.run(
        [sys.executable, str(script)],
        input=stdin if isinstance(stdin, bytes) else stdin.encode(),
        capture_output=True,
        timeout=5,
        check=False,
    )
    if proc.returncode not in (0, 2):
        raise AssertionError(
            f"Hook {script.name} crashed (exit={proc.returncode})\n"
            f"--- stdin ---\n{stdin!r}\n"
            f"--- stderr ---\n{proc.stderr.decode(errors='replace')}"
        )
    return HookResult(exit_code=proc.returncode, stderr=proc.stderr.decode(errors="replace"))


def _run_payload(script: Path, payload: dict) -> HookResult:
    return _run(script, json.dumps(payload))


@pytest.fixture
def run_file_guard_bash():
    def _call(command: str) -> HookResult:
        return _run_payload(
            FILE_GUARD,
            {"tool_name": "Bash", "tool_input": {"command": command}},
        )

    return _call


@pytest.fixture
def run_file_guard_path():
    def _call(tool: str, file_path: str) -> HookResult:
        return _run_payload(
            FILE_GUARD,
            {"tool_name": tool, "tool_input": {"file_path": file_path}},
        )

    return _call


@pytest.fixture
def run_file_guard_raw():
    def _call(stdin: str | bytes) -> HookResult:
        return _run(FILE_GUARD, stdin)

    return _call


@pytest.fixture
def run_file_guard_payload():
    def _call(payload: dict) -> HookResult:
        return _run_payload(FILE_GUARD, payload)

    return _call


def _run_block_git(command: str, cwd: Path | None = None) -> HookResult:
    """Invoke block-dangerous-git.sh with a synthetic Bash PreToolUse payload.

    `cwd` controls the working directory the subprocess sees, which is what
    the hook reads via $(pwd) when the command has no leading `cd` / `git -C`.

    Test isolation: when `cwd` is given, we override $HOME to point at it
    too. The hook expands `~` to $HOME for paths like `cd ~/repo`, and walks
    up directory ancestors looking for a whitelist. On Linux CI where
    TMPDIR can live under the real $HOME, walk-up could otherwise reach
    the developer's actual ~/.claude/safety-hooks.local.md and silently
    leak its contents into the test. Pinning HOME=cwd guarantees the
    subprocess can never see the real home.
    """
    payload = json.dumps({"tool_name": "Bash", "tool_input": {"command": command}})
    env = {**os.environ, "HOME": str(cwd)} if cwd else None
    proc = subprocess.run(
        ["bash", str(BLOCK_GIT)],
        input=payload.encode(),
        capture_output=True,
        timeout=5,
        check=False,
        cwd=str(cwd) if cwd else None,
        env=env,
    )
    if proc.returncode not in (0, 2):
        raise AssertionError(
            f"Hook block-dangerous-git.sh crashed (exit={proc.returncode})\n"
            f"--- stdin ---\n{payload!r}\n"
            f"--- stderr ---\n{proc.stderr.decode(errors='replace')}"
        )
    return HookResult(exit_code=proc.returncode, stderr=proc.stderr.decode(errors="replace"))


@pytest.fixture
def run_block_git():
    """Run block-dangerous-git.sh against an arbitrary command + optional cwd."""

    def _call(command: str, cwd: Path | None = None) -> HookResult:
        return _run_block_git(command, cwd=cwd)

    return _call


@pytest.fixture
def make_whitelist():
    """Create a .claude/safety-hooks.local.md under `root` with `patterns` allowed.

    Returns the path to the created file. Tests that need to verify lookup
    behavior across walk-up / cd-target / git-C paths can place the file at
    different roots and check that the corresponding command form is exempted.
    """

    def _make(root: Path, patterns: list[str]) -> Path:
        claude_dir = root / ".claude"
        claude_dir.mkdir(parents=True, exist_ok=True)
        body = ["---", "allow:"]
        body.extend(f'  - "{p}"' for p in patterns)
        body.append("---")
        body.append("# test fixture")
        wl = claude_dir / "safety-hooks.local.md"
        wl.write_text("\n".join(body) + "\n")
        return wl

    return _make
