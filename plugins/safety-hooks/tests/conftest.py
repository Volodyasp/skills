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
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

import pytest

HOOKS_DIR = Path(__file__).resolve().parent.parent
FILE_GUARD = HOOKS_DIR / "file-guard.py"


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
