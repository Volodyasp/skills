"""`cli` planning of a code round: plan contract, base sources, refusals, intent, REVIEW.md."""

from __future__ import annotations

import json
import os
import re
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from conftest import GitRepo
from helpers_git import (
    APP,
    NEW,
    UTIL,
    Rc,
    app_text,
    assert_error,
    fake_gh,
    gh_calls,
    hide_gh,
    make_rc,
    make_unmerged,
    pr_json,
    seed_branch,
    set_remote_ref,
    snap,
)
from review_cycle.commands import _count

ST1_KEYS = {
    "v", "plan_id", "created_at", "status", "repo_root", "state_dir", "verify_dir", "mode",
    "target", "branch", "base_ref", "base_reason", "merge_base", "head_sha", "tree_sha",
    "doc_sha256", "change_id", "file_ids", "round", "level", "level_source", "model_override",
    "level_config", "small_diff", "scope", "warning", "known", "recheck_file", "recheck",
    "review_md", "rules_files", "intent", "references", "agents_estimate", "workflow",
    "paths", "focus",
}  # fmt: skip
ST3_KEYS = {
    "v", "plan_id", "plan", "mode", "level", "finders", "finder_model", "votes", "tiebreak",
    "sweep", "model_override", "depth", "lens_file", "verifier_section", "verify_dir",
    "state_dir", "intent_file", "review_md", "rules_files", "recheck_file", "recheck",
    "repo_root", "focus", "paths",
}  # fmt: skip


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


def test_new_round_prints_the_cli9_lines_in_order(rc: Rc) -> None:
    """CLI-9 (new round), CLI-1: machine lines, in the documented order."""
    seed_branch(rc.repo, big=True)
    out = rc.cli("high")
    assert out.code == 0, out.err
    assert out.keys == [
        "state", "round", "base", "agents", "intent", "next", "workflow-name", "workflow-args",
    ]  # fmt: skip
    assert Path(out.get("state")).resolve() == rc.state_dir().resolve()
    assert os.path.isabs(out.get("state"))
    assert out.get("round").startswith("1 · code · high · ")
    assert out.get("base") == "main (no PR found via gh)"
    assert out.get("intent") == "none"
    assert out.get("next") == "workflow"
    assert out.get("workflow-name") == "review-cycle:round"
    assert re.fullmatch(
        r"~\d+ \(finders 4 \+ verifiers \d+ \+ tie-break ≤ \d+\)", out.get("agents")
    )


def test_workflow_args_line_is_one_line_json_with_absolute_paths(rc: Rc) -> None:
    """ST-3: all paths absolute, one-line JSON, equal to the plan's stored args."""
    seed_branch(rc.repo)
    out = rc.cli("high")
    assert "\n" not in out.get("workflow-args")
    args = out.args
    assert ST3_KEYS <= set(args)
    plan = rc.plan_json()
    assert args == plan["workflow"]["args"]
    assert plan["workflow"]["name"] == "review-cycle:round"
    for key in ("plan", "state_dir", "verify_dir", "intent_file", "recheck_file", "lens_file"):
        assert os.path.isabs(args[key]), key
    assert os.path.isabs(args["repo_root"])
    assert args["repo_root"] == plan["repo_root"]  # RPT-16
    assert args["plan"] == str(rc.state_dir() / "plan.json")
    assert args["lens_file"].endswith("references/code.md")
    assert args["verifier_section"] == "## Verifier"
    assert args["mode"] == "code" and args["level"] == "high"
    assert args["model_override"] is False
    assert args["plan_id"] == plan["plan_id"]


def test_plan_json_describes_the_round(rc: Rc) -> None:
    """ST-1, RND-2, RND-3, RND-5, RND-9, RND-12: field values of a first round."""
    seed_branch(rc.repo)
    rc.cli("high")
    plan = rc.plan_json()
    assert ST1_KEYS <= set(plan)
    assert plan["v"] == 1 and plan["status"] == "ready" and plan["mode"] == "code"
    assert plan["target"] == "code"
    assert re.fullmatch(r"[0-9a-f]{32}", plan["plan_id"])
    assert re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(\.\d+)?Z", plan["created_at"])
    assert plan["repo_root"] == str(rc.root)
    assert plan["state_dir"] == str(rc.state_dir())
    assert plan["verify_dir"] == str(rc.state_dir() / "verify")
    assert plan["branch"] == "feature/seed"
    assert (plan["base_ref"], plan["base_reason"]) == ("main", "no PR found via gh")
    assert plan["merge_base"] == rc.repo.run("merge-base", "main", "HEAD").strip()
    assert plan["head_sha"] == rc.repo.run("rev-parse", "HEAD").strip()
    assert rc.repo.run("cat-file", "-t", plan["tree_sha"]).strip() == "tree"
    assert re.fullmatch(r"[0-9a-f]{64}", plan["change_id"])
    assert set(plan["file_ids"]) == {APP, NEW}
    assert plan["doc_sha256"] is None
    assert plan["round"] == 1 and plan["level"] == "high" and plan["level_source"] == "typed"
    assert plan["model_override"] is None
    assert plan["known"] == [] and plan["recheck"] == []
    assert plan["references"]["verifier_section"] == "## Verifier"
    assert plan["scope"]["kind"] == "full"
    assert sorted(plan["scope"]["files"]) == [APP, NEW]
    assert plan["scope"]["deleted"] == [] and plan["scope"]["since_round"] is None
    assert plan["scope"]["base_changed_from"] is None
    assert plan["scope"]["lines"] == 3
    est = plan["agents_estimate"]
    assert est["total"] == est["finders"] + est["verifiers"] + est["tiebreak"] + est["sweep"]


def test_plan_leaves_the_branch_clean_and_ignores_its_own_files(rc: Rc) -> None:
    """RND-18, ST-2: `.gitignore *` in the state dir; verifier files only under verify/."""
    seed_branch(rc.repo)
    rc.cli("high")
    sd = rc.state_dir()
    assert (sd / ".gitignore").read_text(encoding="utf-8").strip() == "*"
    assert rc.repo.run("status", "--porcelain") == ""
    verify = {p.name for p in (sd / "verify").iterdir()}
    assert "intent.md" in verify
    assert verify <= {"intent.md", "review-md-base.md", "recheck.json"}
    args = rc.plan_json()["workflow"]["args"]
    for key in ("intent_file", "recheck_file"):
        assert args[key].startswith(str(sd / "verify") + os.sep)


@pytest.mark.parametrize(
    ("branch", "expected"),
    [("feature/a/b", "a/b"), ("work", "work"), ("fix/ünï;code", "-n--code")],
)
def test_state_dir_is_derived_from_the_branch(rc: Rc, branch: str, expected: str) -> None:
    """RND-18: part after the first `/`, unsafe characters become `-`."""
    seed_branch(rc.repo, branch)
    out = rc.cli("high")
    assert out.code == 0, out.err
    state = Path(out.get("state"))
    assert state == rc.root / "agents" / "TEMP" / expected / "review-cycle" / "code"
    assert (state / "plan.json").exists()


def test_branch_clash_refuses_and_fresh_archives(rc: Rc) -> None:
    """RND-18, RND-8: `feature/x` and `fix/x` share a state dir; --fresh archives it."""
    seed_branch(rc.repo, "feature/x")
    rc.round_trip()
    state = rc.state_dir()
    rc.repo.branch("fix/x")
    refused = rc.cli()
    assert_error(
        refused, 1, "belongs to branch feature/x; run with --fresh to start over for fix/x"
    )
    assert str(state) in refused.get("error")
    assert (state / "state.json").exists()
    fresh = rc.cli("--fresh", "high")
    assert fresh.code == 0 and fresh.get("next") == "workflow"
    archives = list(state.glob("archive-*"))
    assert len(archives) == 1 and (archives[0] / "state.json").exists()
    assert not (state / "state.json").exists()
    assert rc.plan_json()["branch"] == "fix/x" and rc.plan_json()["round"] == 1


def test_nothing_to_review_on_a_branch_without_changes(rc: Rc) -> None:
    """RND-6, CLI-9: empty branch diff -> stop with a reason."""
    rc.repo.branch("feature/empty")
    out = rc.cli()
    assert out.code == 0
    assert out.get("next") == "stop"
    assert out.get("reason") == "no changes against main"
    assert "workflow-args" not in out.keys


def test_ignored_files_alone_are_not_a_change(rc: Rc) -> None:
    """RND-5/RND-6: ignored files never enter the snapshot."""
    rc.repo.commit({".gitignore": "*.log\n"}, "ignore logs")
    rc.repo.branch("feature/ignored")
    rc.repo.write("debug.log", "noise\n")
    assert rc.cli().get("next") == "stop"


def test_untracked_and_uncommitted_work_is_part_of_the_round(rc: Rc) -> None:
    """RND-3/RND-5: staged, unstaged, untracked-non-ignored and deleted files; ignored ones not."""
    seed_branch(rc.repo)
    rc.repo.commit({".gitignore": "*.log\n"}, "ignore logs")
    rc.repo.write("src/scratch.py", "print('hi')\n")
    rc.repo.write("debug.log", "noise\n")
    rc.repo.write(APP, app_text(insert={20: "    return risky(x)  # seeded"}) + "more\n")
    (rc.repo.root / UTIL).unlink()
    rc.cli("high")
    plan = rc.plan_json()
    assert {"src/scratch.py", APP, UTIL, NEW} <= set(plan["file_ids"])
    assert "debug.log" not in plan["file_ids"]
    assert plan["scope"]["kind"] == "full"


def test_a_file_that_only_exists_untracked_makes_a_round(rc: Rc) -> None:
    """RND-5: untracked non-ignored file on an otherwise empty branch."""
    rc.repo.branch("feature/wip")
    rc.repo.write("src/scratch.py", "x = 1\n")
    out = rc.cli("high")
    assert out.get("next") == "workflow"
    assert set(rc.plan_json()["file_ids"]) == {"src/scratch.py"}


def test_plan_is_deterministic_apart_from_id_and_time(rc: Rc) -> None:
    """NFR-1."""
    seed_branch(rc.repo)
    rc.cli("high")
    first = rc.plan_json()
    rc.cli("high")
    second = rc.plan_json()
    assert first["plan_id"] != second["plan_id"]

    def stable(plan: dict[str, Any]) -> dict[str, Any]:
        plan = json.loads(json.dumps(plan))
        for key in ("plan_id", "created_at"):
            plan.pop(key)
        plan["workflow"]["args"].pop("plan_id")
        return plan

    assert stable(first) == stable(second)


def test_level_typed_is_remembered_for_the_next_plan(rc: Rc, data_dir: Path) -> None:
    """CLI-5, ST-8: a typed level is written to `last-level`.

    RPT-18 drops the old silent fallback to a remembered or default level: with no level typed,
    `plan` always asks instead (see test_commands_choose.py); this only covers the write.
    """
    seed_branch(rc.repo)
    rc.cli("medium")
    plan = rc.plan_json()
    assert (plan["level"], plan["level_source"]) == ("medium", "typed")
    assert (data_dir / "last-level").read_text(encoding="utf-8") == "medium\n"


def test_model_override_replaces_every_role_model(rc: Rc) -> None:
    """FND-2 via the plan: votes, tie-break and finders use the alias."""
    seed_branch(rc.repo)
    rc.cli("high", "--model", "opus")
    plan = rc.plan_json()
    cfg = plan["level_config"]
    assert plan["model_override"] == "opus"
    assert cfg["votes"] == ["opus", "opus"] and cfg["tiebreak"] == "opus"
    assert cfg["finder_model"] == "opus"
    assert plan["workflow"]["args"]["model_override"] is True


def test_flags_may_come_first(rc: Rc) -> None:
    """CLI-4: tokens in any order, including a leading flag."""
    seed_branch(rc.repo)
    out = rc.cli("--model", "opus", "low")
    assert out.code == 0, out.err
    assert rc.plan_json()["level"] == "low"


def test_small_diff_cuts_finders_to_two(rc: Rc) -> None:
    """RND-13, CLI-9 `small-diff:`."""
    seed_branch(rc.repo)
    out = rc.cli("high")
    assert out.get("small-diff") == "4 → 2 finders"
    assert out.keys.index("small-diff") == out.keys.index("agents") + 1
    plan = rc.plan_json()
    assert plan["small_diff"] == {
        "applied": True, "lines": 3, "files": 2, "max_lines": 50, "max_files": 3,
        "finders_from": 4, "finders_to": 2,
    }  # fmt: skip
    assert [f["lens"] for f in plan["level_config"]["finders"]] == ["bugs", "intent"]


def test_lock_files_do_not_defeat_the_small_diff_cut(rc: Rc) -> None:
    """RND-13: `*.lock` and friends are excluded from the counts."""
    rc.repo.commit({"a.py": "1\n", "b.py": "2\n", "c.py": "3\n"}, "base")
    rc.repo.branch("feature/locks")
    rc.repo.commit(
        {"a.py": "1\n1\n", "b.py": "2\n2\n", "c.py": "3\n3\n", "uv.lock": "x\n" * 200}, "work"
    )
    rc.cli("high")
    small = rc.plan_json()["small_diff"]
    assert small["applied"] is True and small["files"] == 3 and small["lines"] == 3


def test_four_files_or_fifty_one_lines_are_not_small(rc: Rc) -> None:
    """RND-13: both limits are inclusive."""
    rc.repo.commit({"a.py": "1\n"}, "base")
    rc.repo.branch("feature/four")
    rc.repo.commit({f"f{i}.py": "x\n" for i in range(4)}, "four files")
    out = rc.cli("high")
    assert rc.plan_json()["small_diff"]["applied"] is False
    assert "small-diff" not in out.keys


def test_fifty_one_changed_lines_are_not_small(rc: Rc) -> None:
    """RND-13."""
    rc.repo.branch("feature/lines")
    rc.repo.commit({"a.py": "x\n" * 51}, "long file")
    rc.cli("high")
    small = rc.plan_json()["small_diff"]
    assert small["lines"] == 51 and small["applied"] is False


def test_max_level_estimate_names_the_sweep(rc: Rc) -> None:
    """CLI-9 `agents:` with sweep, RND-15."""
    seed_branch(rc.repo, big=True)
    out = rc.cli("max")
    assert re.fullmatch(
        r"~\d+ \(finders 6 \+ verifiers \d+ \+ tie-break ≤ \d+ \+ sweep ≤ 4\)", out.get("agents")
    )
    assert rc.plan_json()["agents_estimate"]["sweep"] == 4


def test_intent_from_commit_messages_only_is_reported_as_none(rc: Rc) -> None:
    """RND-16(b), CLI-9 `intent: none`: commits alone do not count as stated intent."""
    seed_branch(rc.repo)
    out = rc.cli("high")
    intent = rc.plan_json()["intent"]
    assert out.get("intent") == "none"
    assert intent["none"] is True
    kinds = [s["kind"] for s in intent["sources"]]
    assert kinds == ["commit"]
    mb7 = rc.plan_json()["merge_base"][:7]
    head7 = rc.plan_json()["head_sha"][:7]
    assert intent["sources"][0]["ref"] == f"{mb7}..{head7}"
    text = Path(intent["file"]).read_text(encoding="utf-8")
    assert "## Commits" in text and "seed the change" in text


def test_intent_from_pr_body_and_linked_docs(rc: Rc) -> None:
    """RND-16(a)(d): PR body, linked docs tracked at HEAD only, paths not contents."""
    seed_branch(rc.repo)
    set_remote_ref(rc.repo, "origin/main")
    rc.repo.commit(
        {
            "docs/design.md": "DESIGN-BODY-SENTINEL\n",
            "docs/commit-ref.md": "x\n",
        },
        "Implement it, see docs/commit-ref.md",
    )
    rc.repo.write("docs/other.md", "untracked\n")
    body = "Design: docs/design.md, ./docs/other.md, ../outside.md, /etc/abs.md"
    fake_gh(rc.gh_dir, stdout=pr_json("main", 12, "feature/seed", body))
    out = rc.cli("high")
    assert out.get("base") == "origin/main (PR #12)"
    intent = rc.plan_json()["intent"]
    refs = {(s["kind"], s["ref"]) for s in intent["sources"]}
    assert ("pr", "#12") in refs
    assert ("linked", "docs/design.md") in refs and ("linked", "docs/commit-ref.md") in refs
    bad = {"docs/other.md", "../outside.md", "/etc/abs.md"}
    assert not [r for r in refs if r[0] == "linked" and r[1] in bad]
    assert intent["none"] is False
    assert "intent" not in out.keys
    text = Path(intent["file"]).read_text(encoding="utf-8")
    for heading in ("## PR #12", "## Commits", "## Linked"):
        assert heading in text
    assert "docs/design.md" in text and "DESIGN-BODY-SENTINEL" not in text


def test_intent_flag_literal_text_and_files(rc: Rc, tmp_path: Path) -> None:
    """CLI-6: file (repo-relative or absolute) or literal text; adds a source."""
    seed_branch(rc.repo)
    rc.repo.write("notes/why.txt", "Refunds must be idempotent\n")
    outside = tmp_path / "outside-intent.txt"
    outside.write_text("Outside intent text\n", encoding="utf-8")

    rc.cli("high", "--intent", "Make refunds idempotent")
    sources = rc.plan_json()["intent"]["sources"]
    assert {"kind": "flag", "ref": "text"} in sources
    assert any(s["kind"] == "commit" for s in sources)
    assert "Make refunds idempotent" in Path(rc.plan_json()["intent"]["file"]).read_text("utf-8")
    assert rc.plan_json()["intent"]["none"] is False

    rc.cli("high", "--intent", "notes/why.txt")
    assert {"kind": "flag", "ref": "notes/why.txt"} in rc.plan_json()["intent"]["sources"]
    assert "idempotent" in Path(rc.plan_json()["intent"]["file"]).read_text("utf-8")

    rc.cli("high", "--intent", str(outside))
    assert {"kind": "flag", "ref": str(outside)} in rc.plan_json()["intent"]["sources"]
    section = Path(rc.plan_json()["intent"]["file"]).read_text("utf-8")
    assert "## --intent" in section and "Outside intent text" in section


def test_review_md_is_read_at_the_merge_base_not_from_the_branch(rc: Rc) -> None:
    """RND-17: the branch's edit of REVIEW.md is ignored; nit cap from the base copy."""
    rc.repo.commit({"REVIEW.md": "Report at most three nits.\n"}, "add REVIEW.md")
    seed_branch(rc.repo)
    rc.repo.commit({"REVIEW.md": "Report at most one nit.\n"}, "branch edits REVIEW.md")
    rc.cli("high")
    review = rc.plan_json()["review_md"]
    assert review["nit_cap"] == 3
    copy = Path(review["path"])
    assert copy.parent == rc.state_dir() / "verify"
    assert copy.read_text(encoding="utf-8") == "Report at most three nits.\n"


def test_review_md_added_only_on_the_branch_is_ignored(rc: Rc) -> None:
    """RND-17: absent at the merge-base -> path null, default cap."""
    seed_branch(rc.repo)
    rc.repo.commit({"REVIEW.md": "at most one nit\n"}, "branch adds REVIEW.md")
    rc.cli("high")
    assert rc.plan_json()["review_md"] == {"path": None, "nit_cap": 5}


def test_rules_files_are_listed_when_they_exist(rc: Rc) -> None:
    """RND-19: CLAUDE.md, AGENTS.md, .claude/CLAUDE.md at the repo root, absolute paths."""
    rc.repo.commit({"CLAUDE.md": "rules\n", ".claude/CLAUDE.md": "more\n"}, "rules")
    seed_branch(rc.repo)
    rc.cli("high")
    assert rc.plan_json()["rules_files"] == [
        str(rc.root / "CLAUDE.md"),
        str(rc.root / ".claude" / "CLAUDE.md"),
    ]


def test_diff_cmd_prints_the_branchs_own_diff_of_the_scope_files(rc: Rc) -> None:
    """RND-10/RPT-14: `git -c core.quotepath=false diff <merge_base> <tree_sha> -- <files>`."""
    seed_branch(rc.repo)
    rc.cli("high")
    plan = rc.plan_json()
    text = rc.run_diff_cmd(plan)
    assert "+    return risky(x)  # seeded" in text and "+def new():" in text
    assert "core.quotepath=false" in plan["scope"]["diff_cmd"]
    expected = rc.repo.run(
        "-c", "core.quotepath=false", "diff", plan["merge_base"], plan["tree_sha"], "--", APP, NEW
    )
    assert text == expected


# ---------------------------------------------------------------- base sources (RND-1)


def base_of(rc: Rc, *tokens: str) -> str:
    out = rc.cli("high", *tokens)
    assert out.code == 0, out.err
    plan = rc.plan_json()
    assert out.get("base") == f"{plan['base_ref']} ({plan['base_reason']})"
    return out.get("base")


def test_base_when_gh_is_not_installed(rc: Rc, tmp_path: Path) -> None:
    """RND-1.4."""
    seed_branch(rc.repo)
    hide_gh(rc.monkeypatch, rc.gh_dir, tmp_path)
    assert base_of(rc) == "main (gh not installed)"


def test_base_when_gh_finds_no_pr(rc: Rc) -> None:
    """RND-1.4."""
    seed_branch(rc.repo)
    assert base_of(rc) == "main (no PR found via gh)"


def test_base_when_gh_fails(rc: Rc) -> None:
    """RND-1.4: first stderr line, at most 80 characters."""
    seed_branch(rc.repo)
    fake_gh(rc.gh_dir, stderr="HTTP 502: Bad gateway\nmore", code=1)
    assert base_of(rc) == "main (gh error: HTTP 502: Bad gateway)"


def test_base_when_gh_finds_no_remote(rc: Rc) -> None:
    """RPT-17/RND-1."""
    seed_branch(rc.repo)
    fake_gh(rc.gh_dir, stderr="no git remotes found", code=1)
    assert base_of(rc) == "main (no remote for gh)"


def test_round_line_counts_use_singular_and_plural(rc: Rc) -> None:
    """RPT-17/CLI-9: `1 file`, `2 files`, `1 line`."""
    seed_branch(rc.repo)
    plan_line = rc.cli("high").get("round")
    scope = rc.plan_json()["scope"]
    assert plan_line.endswith(f"{len(scope['files'])} files · {scope['lines']} lines")
    assert [_count(n, "file") for n in (0, 1, 2)] == ["0 files", "1 file", "2 files"]


def test_base_is_the_pr_base_when_it_resolves(rc: Rc) -> None:
    """RND-1.3, CLI-9 `base:` example `origin/develop (PR #12)`."""
    seed_branch(rc.repo)
    set_remote_ref(rc.repo, "origin/develop")
    fake_gh(rc.gh_dir, stdout=pr_json("develop", 12, "feature/seed", "body"))
    assert base_of(rc) == "origin/develop (PR #12)"
    assert gh_calls(rc.gh_dir)[0].startswith("pr view")


def test_base_falls_back_when_the_pr_base_is_not_a_local_ref(rc: Rc) -> None:
    """RND-1.4: no fetch; the reason names the missing ref."""
    seed_branch(rc.repo)
    fake_gh(rc.gh_dir, stdout=pr_json("develop", 12, "feature/seed"))
    assert base_of(rc) == "main (PR #12 base origin/develop not found)"


@pytest.mark.parametrize(
    ("present", "expected"),
    [
        ({"main"}, "main"),
        ({"origin/main", "main"}, "origin/main"),
        ({"origin/master"}, "origin/master"),
        ({"master"}, "master"),
    ],
)
def test_base_default_chain(rc: Rc, present: set[str], expected: str) -> None:
    """RND-1.4: first resolving of origin/HEAD, origin/main, origin/master, main, master."""
    seed_branch(rc.repo)
    for name in present:
        if name.startswith("origin/"):
            set_remote_ref(rc.repo, name)
    if "main" not in present:
        if "master" in present:
            rc.repo.run("branch", "master", "main")
        rc.repo.run("branch", "-D", "main")
    assert base_of(rc) == f"{expected} (no PR found via gh)"


def test_no_base_branch_is_an_error(rc: Rc) -> None:
    """RND-1: none resolves."""
    seed_branch(rc.repo)
    rc.repo.run("branch", "-D", "main")
    assert_error(rc.cli(), 1, "no base branch found")


@pytest.mark.parametrize("target", ["release...HEAD", "release...", "release...feature/seed"])
def test_range_target_sets_the_base(rc: Rc, target: str) -> None:
    """RND-1.1, CLI-4: all three right-side forms give base `release (range target)`."""
    seed_branch(rc.repo)
    rc.repo.run("branch", "release", "main")
    assert base_of(rc, target) == "release (range target)"
    assert rc.plan_json()["target"] == "code"


def test_range_target_beats_the_pr_base_but_intent_still_uses_the_pr(rc: Rc) -> None:
    """RND-1.1, RND-16: range wins for the base; PR body still feeds the intent."""
    seed_branch(rc.repo)
    rc.repo.run("branch", "release", "main")
    set_remote_ref(rc.repo, "origin/develop")
    fake_gh(rc.gh_dir, stdout=pr_json("develop", 12, "feature/seed", "Why: idempotency"))
    assert base_of(rc, "release...HEAD") == "release (range target)"
    assert ("pr", "#12") in {(s["kind"], s["ref"]) for s in rc.plan_json()["intent"]["sources"]}


def test_range_with_another_right_side_asks_for_a_checkout(rc: Rc) -> None:
    """CLI-7."""
    seed_branch(rc.repo)
    rc.repo.run("branch", "other", "main")
    assert_error(rc.cli("main...other"), 1, "check out other first")


def test_range_with_an_unknown_base_ref(rc: Rc) -> None:
    """CLI-7."""
    seed_branch(rc.repo)
    assert_error(rc.cli("nosuch...HEAD"), 1, "base ref nosuch not found")


@pytest.mark.parametrize("target", ["#12", "12"])
def test_pr_target_uses_the_pr_base(rc: Rc, target: str) -> None:
    """RND-1.2, CLI-4."""
    seed_branch(rc.repo)
    set_remote_ref(rc.repo, "origin/develop")
    fake_gh(rc.gh_dir, stdout=pr_json("develop", 12, "feature/seed", "body"))
    assert base_of(rc, target) == "origin/develop (PR #12)"
    assert gh_calls(rc.gh_dir)[0].startswith("pr view 12")


def test_pr_target_with_an_unresolvable_base(rc: Rc) -> None:
    """RND-1.2: no fallback chain for a PR target."""
    seed_branch(rc.repo)
    fake_gh(rc.gh_dir, stdout=pr_json("develop", 12, "feature/seed"))
    assert_error(rc.cli("#12"), 1, "PR #12 base origin/develop not found; fetch it first")


def test_pr_target_of_another_branch(rc: Rc) -> None:
    """CLI-7."""
    seed_branch(rc.repo)
    set_remote_ref(rc.repo, "origin/develop")
    fake_gh(rc.gh_dir, stdout=pr_json("develop", 12, "someone/else"))
    assert_error(rc.cli("#12"), 1, "check out someone/else first")


def test_pr_target_needs_a_working_gh(rc: Rc, tmp_path: Path) -> None:
    """CLI-7."""
    seed_branch(rc.repo)
    hide_gh(rc.monkeypatch, rc.gh_dir, tmp_path)
    assert_error(rc.cli("#12"), 1, "PR target needs gh (gh not installed)")


def test_pr_target_with_a_gh_error(rc: Rc) -> None:
    """CLI-7."""
    seed_branch(rc.repo)
    fake_gh(rc.gh_dir, stderr="HTTP 404: not found", code=1)
    out = rc.cli("#12")
    assert_error(out, 1, "PR target needs gh (gh error: HTTP 404: not found)")


# ---------------------------------------------------------------- refusals and exit codes


def test_branch_target_other_than_the_current_branch(rc: Rc) -> None:
    """CLI-7."""
    seed_branch(rc.repo)
    rc.repo.run("branch", "other", "main")
    assert_error(rc.cli("other"), 1, "check out other first")


def test_branch_target_equal_to_the_current_branch_is_fine(rc: Rc) -> None:
    """CLI-4/CLI-7."""
    seed_branch(rc.repo)
    assert rc.cli("feature/seed", "high").get("next") == "workflow"


def test_a_mistyped_level_is_a_branch_name(rc: Rc) -> None:
    """CLI-4/§14: `hi` is not a level, so it is a branch target."""
    seed_branch(rc.repo)
    assert_error(rc.cli("hi"), 1, "check out hi first")


def test_detached_head_is_refused(rc: Rc) -> None:
    """CLI-7."""
    seed_branch(rc.repo)
    rc.repo.run("checkout", "-q", "--detach")
    assert_error(rc.cli(), 1, "detached HEAD; check out a branch")


def test_unmerged_files_are_refused_and_nothing_changes(rc: Rc) -> None:
    """RND-3."""
    seed_branch(rc.repo)
    make_unmerged(rc.repo)
    before = snap(rc.repo)
    assert_error(rc.cli(), 1, "unmerged files; finish the merge first")
    assert snap(rc.repo) == before


@pytest.mark.parametrize(
    "tokens",
    [["--bogus"], ["one", "two"], ["--model", "bad alias"], ["-x"], ["a..b"], ["--intent"]],
)
def test_usage_errors_exit_two(rc: Rc, tokens: list[str]) -> None:
    """CLI-10 exit 2, CLI-4."""
    seed_branch(rc.repo)
    assert rc.cli(*tokens).code == 2


def test_not_a_git_repository_is_an_environment_error(rc: Rc, tmp_path: Path) -> None:
    """CLI-10 exit 3."""
    plain = tmp_path / "plain"
    plain.mkdir()
    out = rc.cli(cwd=plain)
    assert out.code == 3
    assert out.get("next") == "stop"


def test_git_missing_is_an_environment_error(rc: Rc, tmp_path: Path) -> None:
    """CLI-10 exit 3."""
    seed_branch(rc.repo)
    empty = tmp_path / "empty-bin"
    empty.mkdir()
    rc.monkeypatch.setenv("PATH", str(empty))
    assert rc.cli().code == 3


@pytest.mark.parametrize("value", ["", "${CLAUDE_PLUGIN_DATA}", "/x/${CLAUDE_PLUGIN_DATA}/y"])
def test_data_dir_unusable_is_exit_three(rc: Rc, value: str, tmp_path: Path) -> None:
    """CLI-13: empty or containing a literal `${`; checked before anything else."""
    plain = tmp_path / "plain"
    plain.mkdir()
    for argv, cwd in (
        (["cli", "--data-dir", value, "a", "b"], plain),
        (["continue", "--data-dir", value, "--state-dir", str(plain)], plain),
        (["merge", "--data-dir", value, "--state-dir", str(plain), "--result", "r.json"], plain),
    ):
        out = rc.run(argv, cwd)
        assert_error(out, 3, "--data-dir not set (plugin data dir)")


def test_data_dir_absent_is_exit_three_not_a_usage_error(rc: Rc) -> None:
    """CLI-13."""
    seed_branch(rc.repo)
    out = rc.run(["cli"])
    assert_error(out, 3, "--data-dir not set (plugin data dir)")


# ---------------------------------------------------------------- performance (NFR-5)


@pytest.mark.slow
def test_plan_on_a_500_file_branch_takes_under_five_seconds(rc: Rc) -> None:
    """NFR-5: `plan` on 500 files, gh excluded (the fake gh answers at once)."""
    rc.repo.branch("feature/many")
    rc.repo.commit({f"pkg/m{i // 50}/f{i}.py": f"value = {i}\n" for i in range(500)}, "many")
    started = time.perf_counter()
    out = rc.cli("high")
    elapsed = time.perf_counter() - started
    assert out.get("next") == "workflow"
    assert len(rc.plan_json()["file_ids"]) == 500
    assert elapsed < 5.0


def test_diff_cmd_quotes_unusual_file_names(rc: Rc) -> None:
    """RND-10/§13: file names with spaces or quotes are shell-quoted in `diff_cmd`."""
    rc.repo.branch("feature/spaces")
    rc.repo.commit({"my file.py": "a\n", "it's.py": "b\n", "док/файл.py": "c\n"}, "odd names")
    rc.cli("high")
    plan = rc.plan_json()
    out = rc.run_diff_cmd(plan)
    for name in ("my file.py", "it's.py", "док/файл.py"):
        assert f"b/{name}" in out


def test_intent_flag_paths_are_resolved_from_a_subdirectory(rc: Rc) -> None:
    """CLI-6: cwd-relative first, then repo-relative; `ref` is repo-relative."""
    seed_branch(rc.repo)
    rc.repo.write("notes/why.txt", "Refunds must be idempotent\n")
    src = rc.repo.root / "src"
    rc.cli("high", "--intent", "../notes/why.txt", cwd=src)
    assert {"kind": "flag", "ref": "notes/why.txt"} in rc.plan_json()["intent"]["sources"]
    rc.cli("high", "--intent", "notes/why.txt", cwd=src)
    assert {"kind": "flag", "ref": "notes/why.txt"} in rc.plan_json()["intent"]["sources"]
    assert "idempotent" in Path(rc.plan_json()["intent"]["file"]).read_text("utf-8")


def test_pr_target_without_a_pr_names_the_reason(rc: Rc) -> None:
    """CLI-7/RND-1: gh's "no pull requests found" -> `no PR found via gh`."""
    seed_branch(rc.repo)
    assert_error(rc.cli("#12"), 1, "PR target needs gh (no PR found via gh)")


def test_missing_pr_base_and_empty_default_chain(rc: Rc) -> None:
    """RND-1: PR base not local and no default-chain ref -> no base branch found."""
    seed_branch(rc.repo)
    fake_gh(rc.gh_dir, stdout=pr_json("develop", 12, "feature/seed"))
    rc.repo.run("branch", "-D", "main")
    assert_error(rc.cli(), 1, "no base branch found")


def test_unrelated_histories_fail_at_the_merge_base(rc: Rc) -> None:
    """RND-2: no common ancestor -> exit 1."""
    rc.repo.run("checkout", "-q", "--orphan", "feature/orphan")
    rc.repo.run("rm", "-rf", "-q", ".")
    rc.repo.commit({"other.txt": "x\n"}, "unrelated root")
    out = rc.cli()
    assert out.code == 1 and out.get("next") == "stop" and out.has("error")
