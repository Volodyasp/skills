"""End-to-end through `state.py` as a subprocess (ENV-3, CLI-13, §13 shell safety)."""

from __future__ import annotations

import json
import subprocess
from collections.abc import Callable
from pathlib import Path

import pytest
from conftest import GitRepo
from helpers_git import Out, fake_gh, no_pr_stderr, raise_if_unimplemented, seed_branch
from helpers_result import build_result, cand

RunState = Callable[..., "subprocess.CompletedProcess[str]"]


@pytest.fixture
def repo(git_repo: GitRepo, fake_gh_dir: Path) -> GitRepo:
    fake_gh(fake_gh_dir, stderr=no_pr_stderr(), code=1)
    seed_branch(git_repo)
    return git_repo


def run(run_state: RunState, repo: GitRepo, *argv: str) -> Out:
    proc = run_state(*argv, cwd=repo.root)
    raise_if_unimplemented(proc)
    return Out(proc.returncode, proc.stdout, proc.stderr)


def test_full_round_trip(
    run_state: RunState, repo: GitRepo, data_dir: Path, tmp_path: Path
) -> None:
    """CLI-1, CLI-9, CLI-12: cli -> merge -> unchanged report -> mark -> show."""
    planned = run(run_state, repo, "cli", "--data-dir", str(data_dir), "high")
    assert planned.code == 0, planned.err
    assert planned.get("next") == "workflow"
    state_dir = Path(planned.get("state"))
    plan = json.loads((state_dir / "plan.json").read_text(encoding="utf-8"))
    assert planned.args == plan["workflow"]["args"]

    result_path = tmp_path / "round-1-result.json"
    result_path.write_text(json.dumps(build_result(plan, [cand()])), encoding="utf-8")
    merged = run(
        run_state,
        repo,
        "merge",
        "--data-dir",
        str(data_dir),
        "--state-dir",
        str(state_dir),
        "--result",
        str(result_path),
    )
    assert merged.code == 0, merged.err
    assert merged.get("next") == "print-report" and "F1" in merged.report
    assert len(merged.findings_lines()) == 1

    again = run(run_state, repo, "cli", "--data-dir", str(data_dir))
    assert again.get("next") == "print-report"
    assert again.report.startswith("No code change since round 1 — not a new round.")

    marked = run(run_state, repo, "cli", "--data-dir", str(data_dir), "F1", "wontfix", "later")
    assert marked.code == 0 and marked.get("marked") == "F1 wontfix"
    shown = run(run_state, repo, "cli", "--data-dir", str(data_dir), "show", "F1")
    assert shown.code == 0 and shown.get("next") == "print-report"


@pytest.mark.parametrize("value", ["", "${CLAUDE_PLUGIN_DATA}"])
def test_unusable_data_dir_is_exit_three(run_state: RunState, repo: GitRepo, value: str) -> None:
    """CLI-13: empty or an unsubstituted placeholder."""
    out = run(run_state, repo, "cli", "--data-dir", value)
    assert out.code == 3
    assert "error: --data-dir not set (plugin data dir)" in out.err.splitlines()


def test_mark_reason_with_shell_metacharacters_is_stored_verbatim(
    run_state: RunState, repo: GitRepo, data_dir: Path, tmp_path: Path
) -> None:
    """§13/CLI-2: quotes, `$()`, backticks and a newline in one argv token; nothing runs."""
    planned = run(run_state, repo, "cli", "--data-dir", str(data_dir), "high")
    state_dir = Path(planned.get("state"))
    plan = json.loads((state_dir / "plan.json").read_text(encoding="utf-8"))
    result_path = tmp_path / "result.json"
    result_path.write_text(json.dumps(build_result(plan, [cand()])), encoding="utf-8")
    run(
        run_state,
        repo,
        "merge",
        "--data-dir",
        str(data_dir),
        "--state-dir",
        str(state_dir),
        "--result",
        str(result_path),
    )
    reason = 'it\'s "odd" $(touch pwned) `touch pwned2`\nsecond line'
    marked = run(run_state, repo, "cli", "--data-dir", str(data_dir), "F1", "intentional", reason)
    assert marked.code == 0, marked.err
    state = json.loads((state_dir / "state.json").read_text(encoding="utf-8"))
    assert state["findings"][0]["disposition"]["reason"] == reason
    for name in ("pwned", "pwned2"):
        assert not (repo.root / name).exists()
