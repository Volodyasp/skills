"""Scaffold checks: package imports, entry points, harness, SKILL.md size."""

from __future__ import annotations

import importlib
import json
import os
import shutil
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path

import pytest
from conftest import BIN, HARNESS, PLUGIN_DIR, REVIEW_JS, STATE_PY

MODULES = [
    "levels",
    "diffs",
    "rounds",
    "docmode",
    "findings",
    "checksum",
    "result",
    "report",
    "gitio",
    "store",
    "commands",
    "cli",
]
RunState = Callable[..., "subprocess.CompletedProcess[str]"]


@pytest.mark.parametrize("name", MODULES)
def test_module_imports(name: str) -> None:
    assert importlib.import_module(f"review_cycle.{name}")


def test_levels_table_is_filled() -> None:
    from review_cycle.levels import LEVELS

    assert list(LEVELS) == ["low", "medium", "high", "xhigh", "max"]


def test_wrapper_is_executable_and_runs() -> None:
    assert os.access(BIN, os.X_OK)
    proc = subprocess.run(
        [str(BIN), "--help"], capture_output=True, text=True, check=False, timeout=30
    )
    assert proc.returncode == 0
    assert "review-cycle-state" in proc.stdout


def test_wrapper_resolves_through_symlink(tmp_path: Path) -> None:
    link = tmp_path / "linked-review-cycle-state"
    link.symlink_to(BIN)
    proc = subprocess.run(
        [str(link), "--help"], capture_output=True, text=True, check=False, timeout=30
    )
    assert proc.returncode == 0


def test_cli_help_exits_zero(run_state: RunState) -> None:
    proc = run_state("cli", "--help")
    assert proc.returncode == 0


def test_python_version_guard_exits_3() -> None:
    """Run state.py with `sys.version_info` patched to 3.9 via a runner script."""
    runner = (
        "import runpy, sys\n"
        "sys.version_info = (3, 9, 0)\n"
        f"runpy.run_path({str(STATE_PY)!r}, run_name='__main__')\n"
    )
    proc = subprocess.run(
        [sys.executable, "-c", runner], capture_output=True, text=True, check=False, timeout=30
    )
    assert proc.returncode == 3
    assert proc.stderr == "review-cycle needs Python >= 3.10, found 3.9\n"


def test_state_py_has_no_modern_syntax() -> None:
    source = STATE_PY.read_text(encoding="utf-8")
    assert "from __future__" not in source
    assert "match " not in source
    assert " | None" not in source


@pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")
def test_harness_runs_review_js_bare_call() -> None:
    proc = subprocess.run(
        ["node", str(HARNESS), str(REVIEW_JS)],
        input="{}",
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )
    assert proc.returncode == 0, proc.stderr
    out = json.loads(proc.stdout)
    assert out["result"]["started"] is False
    assert out["result"]["reason"] == "no-args"
    assert out["result"]["provenance"] == "review-cycle/workflows/review.js"
    assert out["calls"] == []


def test_skill_md_size_limit() -> None:
    skill = PLUGIN_DIR / "skills" / "review-cycle" / "SKILL.md"
    if not skill.exists():
        pytest.skip("SKILL.md not written yet")
    assert len(skill.read_text(encoding="utf-8")) <= 18_000


SKILL_DIR = PLUGIN_DIR / "skills" / "review-cycle"


def _frontmatter(path: Path) -> list[str]:
    lines = path.read_text(encoding="utf-8").splitlines()
    assert lines[0] == "---"
    return lines[1 : lines.index("---", 1)]


def _headings(path: Path) -> set[str]:
    text = path.read_text(encoding="utf-8")
    return {line for line in text.splitlines() if line.startswith("## ")}


def test_skill_frontmatter_declares_name_flags_and_tools() -> None:
    front = _frontmatter(SKILL_DIR / "SKILL.md")
    assert "name: review-cycle" in front
    # RPT-18: Claude may invoke the skill; missing parameters are asked, never guessed.
    assert not any(line.startswith("disable-model-invocation") for line in front)
    assert any(line.startswith("argument-hint:") for line in front)
    tools = {line.strip()[2:] for line in front if line.startswith("  - ")}
    assert {"Bash(review-cycle-state *)", "Workflow", "Workflow(review-cycle:round)"} <= tools


def test_skill_md_handles_every_next_value() -> None:
    headings = _headings(SKILL_DIR / "SKILL.md")
    expected = {"workflow", "print-report", "ask", "choose"}
    assert {f"## next: {value}" for value in expected} <= headings


def test_skill_md_separates_invariants_from_judgement() -> None:
    headings = _headings(SKILL_DIR / "SKILL.md")
    assert {"## Invariants", "## Judgement", "## Fix cycle"} <= headings


@pytest.mark.parametrize(
    ("reference", "lenses"),
    [
        ("code.md", ["bugs", "intent", "rules", "history", "system-fit"]),
        (
            "document.md",
            ["contradictions-gaps", "code-claims", "ambiguity", "unneeded", "consistency-links"],
        ),
    ],
)
def test_reference_has_every_lens_and_a_verifier(reference: str, lenses: list[str]) -> None:
    headings = _headings(SKILL_DIR / "references" / reference)
    assert {f"## Lens: {name}" for name in lenses} | {"## Verifier"} <= headings
