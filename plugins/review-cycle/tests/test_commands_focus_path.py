"""RPT-19 `--focus` and `--path`: plan contract, scope filtering, path targets, CLI-8."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pytest
from conftest import GitRepo
from helpers_git import Rc, assert_error, fake_gh, gh_calls, make_rc, pr_json, seed_branch
from helpers_result import build_result, cand
from review_cycle import docmode


def path_target(*paths: str) -> str:
    """The `code-path-<slug>` target name for `paths` (RPT-20(a))."""
    return f"code-path-{docmode.path_slug(paths)}"


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


# ---------------------------------------------------------------- --focus


def test_focus_line_in_plan_output_after_small_diff_before_intent(rc: Rc) -> None:
    """RPT-19: `focus:` printed after `small-diff:`, before `intent:`."""
    seed_branch(rc.repo)
    out = rc.cli("high", "--focus", "  refund handling  ")
    assert out.get("focus") == "refund handling"
    assert out.keys.index("small-diff") < out.keys.index("focus") < out.keys.index("intent")


def test_focus_in_workflow_args_and_plan_json_absent_from_state_and_outcomes(rc: Rc) -> None:
    """RPT-19: `focus` reaches plan.json/workflow-args; never state.json or outcomes.jsonl."""
    seed_branch(rc.repo)
    out = rc.cli("high", "--focus", "look here")
    assert out.args["focus"] == "look here"
    plan = rc.plan_json()
    assert plan["focus"] == "look here"
    rc.merge(build_result(plan, [cand()]))
    state = rc.state_json()
    assert "focus" not in state
    assert all("focus" not in o for o in rc.outcomes())


def test_no_focus_means_null_in_plan_and_args_and_no_focus_line(rc: Rc) -> None:
    """RPT-19: `focus: str|null` (ST-1/ST-3); no line printed when absent."""
    seed_branch(rc.repo)
    out = rc.cli("high")
    assert "focus" not in out.keys
    assert rc.plan_json()["focus"] is None
    assert out.args["focus"] is None


def test_unchanged_code_with_focus_forces_a_rerun(rc: Rc) -> None:
    """RPT-19/RND-7: `--focus` on unchanged code forces a rerun (scope `full`), like a level."""
    seed_branch(rc.repo)
    rc.round_trip()
    out = rc.cli("high", "--focus", "look again")
    assert out.get("next") == "workflow"
    assert rc.plan_json()["scope"]["kind"] == "full"
    assert out.get("round").startswith("2 · code · high · full")


def test_unchanged_document_with_focus_forces_a_rerun(rc: Rc) -> None:
    """RPT-19/RND-7: `--focus` works in document mode too."""
    rc.repo.branch("feature/doc")
    rc.repo.write("docs/spec.md", "# Spec\n\ngoal text\n")
    rc.cli("docs/spec.md", "high")
    rc.merge(build_result(rc.plan_json("doc-docs-spec-md")), "doc-docs-spec-md")
    out = rc.cli("docs/spec.md", "high", "--focus", "clarity")
    assert out.get("next") == "workflow"
    assert rc.plan_json("doc-docs-spec-md")["scope"]["kind"] == "full"


# ---------------------------------------------------------------- --focus parse errors (CLI-10)


@pytest.mark.parametrize(
    "tokens",
    [["high", "--focus"], ["high", "--focus", ""], ["high", "--focus", "x" * 501]],
)
def test_focus_parse_errors_exit_two(rc: Rc, tokens: list[str]) -> None:
    seed_branch(rc.repo)
    assert rc.cli(*tokens).code == 2


# ---------------------------------------------------------------- --path parse errors (CLI-10)


@pytest.mark.parametrize(
    "tokens",
    [
        ["high", "--path"],
        ["high", "--path", ""],
        ["high", "--path", "-x"],
        ["docs/x.md", "--path", "src"],
    ],
)
def test_path_parse_errors_exit_two(rc: Rc, tokens: list[str]) -> None:
    seed_branch(rc.repo)
    rc.repo.write("docs/x.md", "# X\n")
    assert rc.cli(*tokens).code == 2


# ---------------------------------------------------------------- --path filtering and targets


def three_dirs_branch(rc: Rc) -> None:
    rc.repo.commit({"src/a.py": "1\n", "lib/b.py": "2\n", "docs/c.py": "3\n"}, "base")
    rc.repo.branch("feature/paths")
    rc.repo.commit(
        {"src/a.py": "1\n1\n", "lib/b.py": "2\n2\n", "docs/c.py": "3\n3\n"}, "touch all three"
    )


def test_path_filters_scope_files_and_diff_cmd(rc: Rc) -> None:
    three_dirs_branch(rc)
    out = rc.cli("high", "--path", "src")
    assert out.get("next") == "workflow"
    plan = rc.plan_json(path_target("src"))
    assert set(plan["file_ids"]) == {"src/a.py"}
    assert plan["scope"]["files"] == ["src/a.py"]
    text = rc.run_diff_cmd(plan)
    assert "a.py" in text and "b.py" not in text and "c.py" not in text


def test_two_paths_sorted_slug_and_paths_line(rc: Rc) -> None:
    three_dirs_branch(rc)
    out = rc.cli("high", "--path", "lib", "--path", "src")
    assert out.get("paths") == "lib, src"
    assert out.keys.index("base") < out.keys.index("paths")
    plan = rc.plan_json(path_target("lib", "src"))
    assert set(plan["file_ids"]) == {"src/a.py", "lib/b.py"}
    assert plan["paths"] == ["lib", "src"]
    assert out.args["paths"] == ["lib", "src"]


def test_workflow_arg_paths_is_null_without_a_path_filter(rc: Rc) -> None:
    """RPT-20(c): ST-3 `paths: list[str]|null`."""
    seed_branch(rc.repo)
    out = rc.cli("high")
    assert out.args["paths"] is None
    assert rc.plan_json()["paths"] == []


def test_path_order_does_not_change_the_target_slug(rc: Rc) -> None:
    """RPT-19/RPT-20(a): the slug is built from the sorted unique paths, order given doesn't
    matter, and the slug always ends in a hash of the exact joined paths."""
    three_dirs_branch(rc)
    out = rc.cli("high", "--path", "src", "--path", "lib")
    assert out.get("next") == "workflow"
    assert (rc.state_dir(target=path_target("lib", "src")) / "plan.json").exists()
    assert path_target("src", "lib") == path_target("lib", "src")


def test_path_slug_disambiguates_sanitisation_collisions(rc: Rc) -> None:
    """RPT-20(a): `src/a-b` and `src/a/b` sanitise to the same text but get separate state
    dirs."""
    rc.repo.commit({"src/a-b": "1\n", "src/a/b": "2\n"}, "base")
    rc.repo.branch("feature/collide")
    rc.repo.commit({"src/a-b": "1\n1\n", "src/a/b": "2\n2\n"}, "touch both")
    dash = rc.cli("high", "--path", "src/a-b")
    slash = rc.cli("high", "--path", "src/a/b")
    assert dash.get("next") == "workflow" and slash.get("next") == "workflow"
    assert path_target("src/a-b") != path_target("src/a/b")
    assert set(rc.plan_json(path_target("src/a-b"))["file_ids"]) == {"src/a-b"}
    assert set(rc.plan_json(path_target("src/a/b"))["file_ids"]) == {"src/a/b"}


def test_bad_path_with_a_pr_target_fails_before_calling_gh(rc: Rc, tmp_path: Path) -> None:
    """RPT-20(b): `--path` resolves right after the target checks, before any gh/PR lookup."""
    seed_branch(rc.repo)
    fake_gh(rc.gh_dir, stdout=pr_json("main", 12, "feature/seed", "body"))
    outside = (tmp_path / "outside").resolve()
    out = rc.cli("#12", "--path", str(outside))
    assert out.code == 1
    assert f"--path {outside} is outside" in out.get("error")
    assert gh_calls(rc.gh_dir) == []


def test_path_outside_the_repository_is_an_error(rc: Rc, tmp_path: Path) -> None:
    seed_branch(rc.repo)
    outside = (tmp_path / "outside").resolve()
    assert_error(rc.cli("high", "--path", str(outside)), 1, f"--path {outside} is outside")


def test_path_equal_to_the_repo_root_is_an_error(rc: Rc) -> None:
    seed_branch(rc.repo)
    assert_error(rc.cli("high", "--path", str(rc.root)), 1, "covers the whole repository; drop it")
    assert_error(rc.cli("high", "--path", "."), 1, "covers the whole repository; drop it")


def test_nothing_under_path_prints_the_stop_line(rc: Rc) -> None:
    three_dirs_branch(rc)
    out = rc.cli("high", "--path", "nope")
    assert out.get("next") == "stop"
    assert out.get("reason") == "no changes under nope against main"


def test_path_target_and_whole_branch_target_keep_separate_state_dirs(rc: Rc) -> None:
    three_dirs_branch(rc)
    whole, _ = rc.round_trip()
    path_out = rc.cli("high", "--path", "src")
    assert path_out.get("next") == "workflow"
    target = path_target("src")
    path_plan = rc.plan_json(target)
    assert whole["target"] == "code"
    assert path_plan["target"] == target
    assert rc.state_dir(target="code") != rc.state_dir(target=target)
    rc.merge(build_result(path_plan, [cand(path="src/a.py", symbol="f")]), target)
    whole_state = rc.state_json("code")
    path_state = rc.state_json(target)
    assert len(path_state["findings"]) == 1
    assert whole_state["findings"] == []


def test_mark_and_show_find_findings_in_a_path_target(rc: Rc) -> None:
    three_dirs_branch(rc)
    rc.cli("high", "--path", "src")
    target = path_target("src")
    plan = rc.plan_json(target)
    rc.merge(build_result(plan, [cand(path="src/a.py", symbol="f")]), target)
    marked = rc.cli("F1", "wontfix", "later")
    assert marked.code == 0 and marked.get("marked") == "F1 wontfix"
    shown = rc.cli("show", "F1")
    assert shown.code == 0 and shown.get("next") == "print-report"
