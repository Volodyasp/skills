"""RPT-21 range targets in words: `HEAD~N...HEAD`, `HEAD...HEAD`, combined with `--path`."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pytest
from conftest import GitRepo
from helpers_git import UTIL, Rc, append_commit, make_rc, seed_branch
from helpers_result import build_result
from review_cycle import docmode


@pytest.fixture
def rc(
    git_repo: GitRepo,
    data_dir: Path,
    run_cli: Callable[[list[str], Path], tuple[int, str, str]],
    fake_gh_dir: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> Rc:
    return make_rc(git_repo, data_dir, run_cli, fake_gh_dir, tmp_path, monkeypatch)


def test_head_minus_one_range_plans_last_commit_and_uncommitted(rc: Rc) -> None:
    """`HEAD~1...HEAD` = the last commit's changes plus whatever is uncommitted, nothing from
    earlier commits on the branch."""
    seed_branch(rc.repo)
    append_commit(rc.repo, UTIL, "# second commit")
    rc.repo.write("src/scratch.py", "uncommitted = 1\n")
    out = rc.cli("high", "HEAD~1...HEAD")
    assert out.get("next") == "workflow"
    target = docmode.code_target("HEAD~1", [])
    plan = rc.plan_json(target)
    assert set(plan["file_ids"]) == {UTIL, "src/scratch.py"}


def test_head_dotdotdot_head_plans_only_uncommitted(rc: Rc) -> None:
    """`HEAD...HEAD` = only uncommitted changes."""
    seed_branch(rc.repo)
    rc.repo.write("src/scratch.py", "uncommitted = 1\n")
    out = rc.cli("high", "HEAD...HEAD")
    assert out.get("next") == "workflow"
    target = docmode.code_target("HEAD", [])
    plan = rc.plan_json(target)
    assert set(plan["file_ids"]) == {"src/scratch.py"}


def test_head_dotdotdot_head_on_a_clean_tree_is_nothing_to_review(rc: Rc) -> None:
    seed_branch(rc.repo)
    out = rc.cli("high", "HEAD...HEAD")
    assert out.get("next") == "stop"
    assert out.get("reason") == "no changes against HEAD"


def test_range_target_and_whole_branch_keep_separate_state_dirs(rc: Rc) -> None:
    seed_branch(rc.repo)
    whole, _ = rc.round_trip()
    rc.repo.write("src/scratch.py", "uncommitted = 1\n")
    range_out = rc.cli("high", "HEAD...HEAD")
    assert range_out.get("next") == "workflow"
    target = docmode.code_target("HEAD", [])
    assert target != "code"
    assert rc.state_dir(target="code") != rc.state_dir(target=target)
    range_plan = rc.plan_json(target)
    assert whole["target"] == "code"
    assert range_plan["target"] == target


def test_range_with_path_combined_target_name(rc: Rc) -> None:
    seed_branch(rc.repo)
    append_commit(rc.repo, UTIL, "# second commit")
    out = rc.cli("high", "HEAD~1...HEAD", "--path", UTIL)
    assert out.get("next") == "workflow"
    target = docmode.code_target("HEAD~1", [UTIL])
    assert target.startswith("code-range-head-1-path-")
    plan = rc.plan_json(target)
    assert set(plan["file_ids"]) == {UTIL}
    assert plan["paths"] == [UTIL]


def test_path_only_target_naming_is_unchanged(rc: Rc) -> None:
    """RPT-20(a) naming for a path-only target must not move: a self-review already created
    `code-path-plugins-review-cycle-077560` for `--path plugins/review-cycle`."""
    rc.repo.commit({"plugins/review-cycle/x.py": "1\n"}, "base")
    rc.repo.branch("feature/pin")
    rc.repo.commit({"plugins/review-cycle/x.py": "1\n1\n"}, "edit")
    out = rc.cli("high", "--path", "plugins/review-cycle")
    assert out.get("next") == "workflow"
    pinned = "code-path-plugins-review-cycle-077560"
    assert docmode.code_target(None, ["plugins/review-cycle"]) == pinned
    assert (rc.state_dir(target=pinned) / "plan.json").exists()


def test_range_cycle_second_round_with_moved_head_has_no_base_changed(rc: Rc) -> None:
    """RPT-21: the range's base ref is the literal typed text, constant for the cycle, so a
    moved HEAD never triggers RND-20's `base changed` line."""
    seed_branch(rc.repo)
    append_commit(rc.repo, UTIL, "# first extra")
    target = docmode.code_target("HEAD~1", [])
    out1 = rc.cli("high", "HEAD~1...HEAD")
    assert out1.get("next") == "workflow"
    rc.merge(build_result(rc.plan_json(target)), target)
    append_commit(rc.repo, UTIL, "# second extra")
    out2 = rc.cli("high", "--full", "HEAD~1...HEAD")
    assert out2.get("next") == "workflow"
    assert "base changed" not in out2.keys
    plan2 = rc.plan_json(target)
    assert plan2["scope"]["kind"] == "full"
    assert plan2["base_ref"] == "HEAD~1"
