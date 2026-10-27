"""Round scenarios: unchanged runs, rebases, scope by round, re-checks, --fresh, round 4."""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from pathlib import Path

import pytest
from conftest import GitRepo
from helpers_git import (
    APP,
    NEW,
    UTIL,
    Out,
    Rc,
    app_text,
    append_commit,
    make_rc,
    seed_branch,
    set_remote_ref,
    tree_bytes,
)
from helpers_result import SEEDED, build_result, cand

MAIN_FAR_EDITS = {2: "line 2 edited on main", 38: "line 38 edited on main"}
C_APP = cand()
C_DIV = cand(
    path=UTIL, line=2, symbol="f", snippet="    x = a / b", claim="division by zero", cls="div"
)
C_REJ = cand(
    path=UTIL,
    line=3,
    symbol="f",
    snippet="    y = rejected_line(a)",
    claim="rejected_line is undefined",
    category="error-handling",
    cls="undefined name",
)


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


def main_edits_far_from_the_branch_hunk(rc: Rc) -> None:
    """Commit on main two lines away from the branch's hunk, then return to the branch."""
    branch = rc.repo.run("rev-parse", "--abbrev-ref", "HEAD").strip()
    rc.repo.checkout("main")
    rc.repo.commit({APP: app_text(replace=MAIN_FAR_EDITS)}, "main edits far away")
    rc.repo.checkout(branch)


def assert_unchanged(out: Out, n: int) -> None:
    assert out.code == 0, out.err
    assert out.get("next") == "print-report"
    assert out.report.startswith(f"No code change since round {n} — not a new round.")
    assert "workflow-args" not in out.keys


def test_unchanged_code_prints_the_previous_report(rc: Rc) -> None:
    """RND-7, CLI-9, RPT-1: no new round; the state is not touched."""
    seed_branch(rc.repo)
    rc.round_trip(candidates=[C_APP])
    before = tree_bytes(rc.state_dir())
    out = rc.cli()
    assert_unchanged(out, 1)
    assert "F1" in out.report
    assert (rc.state_dir() / "state.json").read_bytes() == before["state.json"]
    assert rc.state_json()["round"] == 1


def test_empty_commit_is_not_a_round(rc: Rc) -> None:
    """RND-5/RND-7."""
    seed_branch(rc.repo)
    rc.round_trip()
    rc.repo.commit({}, "empty commit")
    assert_unchanged(rc.cli(), 1)


def test_clean_merge_of_the_base_is_not_a_round(rc: Rc) -> None:
    """RND-5/RND-7: base edits >= 2 lines from the branch hunk keep the change id."""
    seed_branch(rc.repo)
    rc.round_trip()
    main_edits_far_from_the_branch_hunk(rc)
    rc.repo.run("merge", "--no-edit", "main")
    assert_unchanged(rc.cli(), 1)


def test_clean_rebase_is_not_a_round(rc: Rc) -> None:
    """RND-5/RND-7."""
    seed_branch(rc.repo)
    rc.round_trip()
    main_edits_far_from_the_branch_hunk(rc)
    rc.repo.run("rebase", "main")
    assert_unchanged(rc.cli(), 1)


def test_committing_the_reviewed_wip_is_not_a_round(rc: Rc) -> None:
    """RND-5/RND-7: uncommitted changes reviewed in round 1, committed afterwards."""
    seed_branch(rc.repo)
    rc.repo.write(UTIL, "def f(a, b):\n    return b\n")
    rc.round_trip()
    rc.repo.run("add", "-A")
    rc.repo.run("commit", "-q", "-m", "wip")
    assert_unchanged(rc.cli(), 1)


def _move_seeded_line(rc: Rc) -> None:
    rc.repo.commit({APP: app_text(insert={30: SEEDED})}, "move the added line")


def _whitespace_only(rc: Rc) -> None:
    rc.repo.commit({APP: app_text(insert={20: SEEDED + " "})}, "trailing blank")


def _untracked_file(rc: Rc) -> None:
    rc.repo.write("src/extra.py", "x = 1\n")


def _uncommitted_edit(rc: Rc) -> None:
    rc.repo.write(UTIL, "def f(a, b):\n    return b\n")


@pytest.mark.parametrize(
    "change", [_move_seeded_line, _whitespace_only, _untracked_file, _uncommitted_edit]
)
def test_real_changes_start_a_new_round(rc: Rc, change: Callable[[Rc], None]) -> None:
    """RND-5: a moved added line, whitespace, an untracked file, an uncommitted edit."""
    seed_branch(rc.repo)
    rc.round_trip()
    change(rc)
    out = rc.cli("high", "--full")
    assert out.get("next") == "workflow"
    assert out.get("round").startswith("2 · code · ")


def test_rebase_onto_a_base_that_changed_an_in_scope_file_keeps_base_code_out(rc: Rc) -> None:
    """RND-10: main edited app.py elsewhere; the round's diff holds none of main's lines."""
    seed_branch(rc.repo)
    rc.round_trip()
    main_edits_far_from_the_branch_hunk(rc)
    rc.repo.run("rebase", "main")
    append_commit(rc.repo, UTIL, "# real edit")
    out = rc.cli("high", "--full")
    assert out.get("round").startswith("2 · ")
    text = rc.run_diff_cmd(rc.plan_json())
    assert "edited on main" not in text
    assert "+" + SEEDED in text and "# real edit" in text
    assert rc.plan_json()["scope"]["kind"] == "full"


def test_scope_since_lists_only_files_changed_after_the_previous_round(rc: Rc) -> None:
    """RND-9/RND-10: round 3 re-reviews changed files; diff_cmd shows only those."""
    seed_branch(rc.repo)
    rc.round_trip()
    rc.round_trip(edit=lambda: append_commit(rc.repo, UTIL, "# second"))
    append_commit(rc.repo, UTIL, "# third")
    out = rc.cli("high", "--incremental")
    plan = rc.plan_json()
    assert out.get("round").startswith("3 · ")
    assert plan["scope"]["kind"] == "since" and plan["scope"]["since_round"] == 2
    assert plan["scope"]["files"] == [UTIL] and plan["scope"]["deleted"] == []
    assert plan["scope"]["lines"] == 2
    text = rc.run_diff_cmd(plan)
    assert "src/util.py" in text and "src/app.py" not in text
    assert set(plan["file_ids"]) == {APP, NEW, UTIL}


def test_scope_since_reports_files_dropped_from_the_branch_diff(rc: Rc) -> None:
    """RND-9: a file whose branch diff vanished is `deleted`."""
    seed_branch(rc.repo)
    rc.round_trip()
    rc.round_trip(edit=lambda: append_commit(rc.repo, UTIL, "# second"))
    rc.repo.run("rm", "-q", NEW)
    append_commit(rc.repo, UTIL, "# third")
    rc.cli("high", "--incremental")
    scope = rc.plan_json()["scope"]
    assert scope["files"] == [UTIL] and scope["deleted"] == [NEW]


def test_routine_rebase_keeps_scope_since_not_full(rc: Rc) -> None:
    """RND-20/RND-9: the merge-base moved, the base ref did not."""
    seed_branch(rc.repo)
    rc.round_trip()
    plan2, _ = rc.round_trip(edit=lambda: append_commit(rc.repo, UTIL, "# second"))
    main_edits_far_from_the_branch_hunk(rc)
    rc.repo.run("rebase", "main")
    append_commit(rc.repo, UTIL, "# third")
    out = rc.cli("high", "--incremental")
    plan3 = rc.plan_json()
    assert plan3["merge_base"] != plan2["merge_base"]
    assert plan3["scope"]["kind"] == "since" and plan3["scope"]["files"] == [UTIL]
    assert "base changed" not in out.keys


def test_missing_file_ids_in_the_state_fall_back_to_full(rc: Rc) -> None:
    """RND-9: no `file_ids` in state.json -> scope `full_fallback`."""
    seed_branch(rc.repo)
    rc.round_trip()
    rc.round_trip(edit=lambda: append_commit(rc.repo, UTIL, "# second"))
    state = rc.state_json()
    del state["file_ids"]
    rc.write_state(state)
    append_commit(rc.repo, UTIL, "# third")
    rc.cli("high", "--incremental")
    scope = rc.plan_json()["scope"]
    assert scope["kind"] == "full_fallback" and set(scope["files"]) == {APP, NEW, UTIL}


def test_a_changed_base_ref_makes_the_scope_full(rc: Rc) -> None:
    """RND-20, CLI-9 `base changed:`: no archive, previous ref in the plan."""
    seed_branch(rc.repo)
    rc.round_trip()
    rc.round_trip(edit=lambda: append_commit(rc.repo, UTIL, "# second"))
    set_remote_ref(rc.repo, "origin/main")
    append_commit(rc.repo, UTIL, "# third")
    out = rc.cli("high", "--full")
    plan = rc.plan_json()
    assert out.get("base changed") == "main → origin/main; full scope"
    assert out.keys.index("base changed") == out.keys.index("base") + 1
    assert plan["scope"]["kind"] == "full_base_changed"
    assert plan["scope"]["base_changed_from"] == "main"
    assert set(plan["scope"]["files"]) == {APP, NEW, UTIL}
    assert not list(rc.state_dir().glob("archive-*"))
    rc.merge(build_result(plan))
    assert rc.state_json()["base_ref"] == "origin/main"


def test_a_changed_base_ref_in_round_two_is_announced(rc: Rc) -> None:
    """RPT-18: the old RND-20 round >= 3 restriction is gone; round 2 already announces it."""
    seed_branch(rc.repo)
    rc.round_trip()
    set_remote_ref(rc.repo, "origin/main")
    append_commit(rc.repo, UTIL, "# second")
    out = rc.cli("high", "--full")
    assert out.get("base changed") == "main → origin/main; full scope"
    assert rc.plan_json()["scope"]["kind"] == "full_base_changed"


def test_a_changed_base_ref_alone_does_not_start_a_round(rc: Rc) -> None:
    """RND-7/RND-20: unchanged code first; the base-change rule applies after it."""
    seed_branch(rc.repo)
    rc.round_trip()
    rc.round_trip(edit=lambda: append_commit(rc.repo, UTIL, "# second"))
    set_remote_ref(rc.repo, "origin/main")
    assert_unchanged(rc.cli(), 2)


def test_fresh_archives_the_state_and_starts_over(rc: Rc) -> None:
    """RND-8: archive incl. verify/, empty findings/rejected/rounds, nothing suppressed."""
    seed_branch(rc.repo, util_findings=True)
    rc.round_trip(candidates=[C_APP, C_REJ], votes={"N1.2": [False, False]})
    state = rc.state_json()
    assert len(state["findings"]) == 1 and len(state["rejected"]) == 1
    sd = rc.state_dir()
    out = rc.cli("--fresh", "high")
    assert out.get("next") == "workflow" and out.get("round").startswith("1 · ")
    (archive,) = sd.glob("archive-*")
    assert re.fullmatch(r"archive-\d{8}T\d{6}Z", archive.name)
    for name in ("state.json", "plan.json", "round-1.md", "verify"):
        assert (archive / name).exists(), name
    assert not (sd / "state.json").exists()
    plan = rc.plan_json()
    assert plan["round"] == 1 and plan["known"] == [] and plan["recheck"] == []
    rc.merge(build_result(plan, [C_APP, C_REJ]))
    fresh = rc.state_json()
    assert [f["id"] for f in fresh["findings"]] == ["F1", "F2"]
    assert fresh["rejected"] == [] and len(fresh["rounds"]) == 1
    assert fresh["rounds"][0]["held_back"]["rejected_suppressed"] == 0


def test_fresh_on_unchanged_code_still_starts_a_round(rc: Rc) -> None:
    """RND-8."""
    seed_branch(rc.repo)
    rc.round_trip()
    assert rc.cli("--fresh", "high").get("next") == "workflow"


KNOWN_KEYS = {"id", "category", "class", "path", "symbol", "claim", "status"}


def test_another_typed_level_on_unchanged_code_reruns_the_whole_branch(rc: Rc) -> None:
    """RND-7/RND-9/RND-11/RND-12: forced rerun = full scope + no-repeat list + re-check."""
    seed_branch(rc.repo)
    rc.round_trip(candidates=[C_APP])
    out = rc.cli("low")
    plan = rc.plan_json()
    assert out.get("next") == "workflow" and out.get("round").startswith("2 · code · low · ")
    assert plan["scope"]["kind"] == "full" and set(plan["scope"]["files"]) == {APP, NEW}
    assert [k["id"] for k in plan["known"]] == ["F1"]
    assert set(plan["known"][0]) == KNOWN_KEYS and plan["known"][0]["status"] == "open"
    assert plan["recheck"] == [{"id": "F1", "path": APP}]
    assert plan["level_source"] == "typed"


def test_full_flag_on_unchanged_code_reruns_and_round_three_stays_full(rc: Rc) -> None:
    """RND-7/RND-9: --full beats `since`, also from round 3 on."""
    seed_branch(rc.repo)
    rc.round_trip(candidates=[C_APP])
    assert rc.cli("--full", "high").get("next") == "workflow"
    assert rc.plan_json()["scope"]["kind"] == "full"
    rc.merge(build_result(rc.plan_json()))
    out = rc.cli("--full", "high")
    assert out.get("round").startswith("3 · ")
    assert rc.plan_json()["scope"]["kind"] == "full"


def test_same_or_remembered_level_on_unchanged_code_is_not_a_rerun(rc: Rc) -> None:
    """RND-7/CLI-5: typing the level of the last round, or none, prints the report."""
    seed_branch(rc.repo)
    rc.round_trip(tokens=["low"])
    assert_unchanged(rc.cli("low"), 1)
    assert_unchanged(rc.cli(), 1)


def test_no_repeat_list_and_rejected_entries_follow_the_snippet(rc: Rc) -> None:
    """RND-11, FND-10: fixed findings leave the list; rejected ones stay while the code does."""
    seed_branch(rc.repo, util_findings=True)
    rc.round_trip(candidates=[C_APP, C_DIV, C_REJ], votes={"N1.3": [False, False]})
    rc.repo.commit({UTIL: "def f(a, b):\n    y = rejected_line(a)\n    return a\n"}, "drop x")
    assert rc.cli("high", "--full").get("next") == "workflow"
    plan2 = rc.plan_json()
    assert sorted(k["id"] for k in plan2["known"]) == ["-", "F1", "F2"]
    rejected = next(k for k in plan2["known"] if k["id"] == "-")
    assert set(rejected) == KNOWN_KEYS and rejected["path"] == UTIL
    assert rejected["class"] == "undefined name"
    assert sorted(r["id"] for r in plan2["recheck"]) == ["F1", "F2"]

    rc.merge(
        build_result(
            plan2,
            [C_REJ],
            recheck={"F1": [True, True], "F2": [False, False]},
        )
    )
    state = rc.state_json()
    statuses = {f["id"]: f["status"] for f in state["findings"]}
    assert statuses == {"F1": "open", "F2": "fixed"}
    assert state["rounds"][1]["held_back"]["rejected_suppressed"] == 1
    assert len(state["rejected"]) == 1

    rc.repo.commit({UTIL: "def f(a, b):\n    return a\n"}, "drop the rejected line")
    assert rc.cli("high", "--full").get("next") == "workflow"
    plan3 = rc.plan_json()
    assert [k["id"] for k in plan3["known"]] == ["F1"]
    assert len(rc.state_json()["rejected"]) == 1


def recheck_setup(rc: Rc) -> None:
    seed_branch(rc.repo)
    rc.round_trip(candidates=[C_APP])


def test_recheck_file_holds_only_the_verifier_fields(rc: Rc) -> None:
    """ST-2, RND-12: `verify/recheck.json` = [{id, path, line, symbol, snippet, claim}]."""
    recheck_setup(rc)
    append_commit(rc.repo, UTIL, "# edit")
    rc.cli("high", "--full")
    plan = rc.plan_json()
    data = json.loads(Path(plan["recheck_file"]).read_text(encoding="utf-8"))
    assert Path(plan["recheck_file"]).parent == rc.state_dir() / "verify"
    assert len(data) == 1
    assert set(data[0]) == {"id", "path", "line", "symbol", "snippet", "claim"}
    assert (data[0]["id"], data[0]["path"], data[0]["symbol"]) == ("F1", APP, "handler")
    assert data[0]["snippet"].strip() == SEEDED.strip()
    assert plan["workflow"]["args"]["recheck"]


def test_recheck_closes_a_finding_when_the_code_moved(rc: Rc) -> None:
    """FND-18 (all refute, code moved), ST-7, RPT-2: fixed + outcome + closed line."""
    recheck_setup(rc)
    rc.repo.commit({APP: app_text()}, "remove the risky line")
    rc.cli("high", "--full")
    rc.merge(build_result(rc.plan_json(), recheck={"F1": [False, False]}))
    state = rc.state_json()
    assert state["findings"][0]["status"] == "fixed"
    assert state["rounds"][1]["fixed"] == ["F1"]
    assert [o["status"] for o in rc.outcomes()] == ["fixed"]
    shown = rc.cli()
    assert shown.get("next") == "print-report"
    assert "Closed since round 1: F1 (fixed)" in shown.report


def test_recheck_closes_a_finding_when_only_the_file_changed_around_it(rc: Rc) -> None:
    """FND-18: snippet still present but the file's diff-id changed counts as moved."""
    recheck_setup(rc)
    rc.repo.commit({APP: app_text(replace={5: "line 5 edited"}, insert={20: SEEDED})}, "edit")
    rc.cli("high", "--full")
    rc.merge(build_result(rc.plan_json(), recheck={"F1": [False, False]}))
    assert rc.state_json()["findings"][0]["status"] == "fixed"


def test_recheck_on_unchanged_code_does_not_close_the_finding(rc: Rc) -> None:
    """FND-18 (all refute, code not moved): stays open, uncertain."""
    recheck_setup(rc)
    rc.cli("high", "--full")
    rc.merge(build_result(rc.plan_json(), recheck={"F1": [False, False]}))
    finding = rc.state_json()["findings"][0]
    assert finding["status"] == "open" and finding["verdict"] == "uncertain"
    assert rc.outcomes() == []


def test_recheck_with_a_holding_verdict_keeps_the_finding_open(rc: Rc) -> None:
    """FND-18 (>= 1 holds)."""
    recheck_setup(rc)
    rc.repo.commit({APP: app_text()}, "remove the risky line")
    rc.cli("high", "--full")
    rc.merge(build_result(rc.plan_json(), recheck={"F1": [True, True]}))
    finding = rc.state_json()["findings"][0]
    assert finding["status"] == "open" and finding["last_seen_round"] == 2


def test_recheck_without_any_returned_verdict_changes_nothing(rc: Rc) -> None:
    """FND-18 (none returned)."""
    recheck_setup(rc)
    append_commit(rc.repo, UTIL, "# edit")
    rc.cli("high", "--full")
    before = rc.state_json()["findings"][0]
    rc.merge(build_result(rc.plan_json(), recheck={"F1": [None, None]}))
    assert rc.state_json()["findings"][0] == before


def test_only_open_findings_are_rechecked(rc: Rc) -> None:
    """RND-12: a finding the owner decided is not re-verified."""
    seed_branch(rc.repo, util_findings=True)
    rc.round_trip(candidates=[C_APP, C_DIV])
    assert rc.cli("F2", "intentional", "on purpose").code == 0
    append_commit(rc.repo, APP, "# edit")
    rc.cli("high", "--full")
    assert [r["id"] for r in rc.plan_json()["recheck"]] == ["F1"]


def three_rounds_with_a_surviving_finding(rc: Rc) -> None:
    seed_branch(rc.repo)
    rc.round_trip(candidates=[C_APP])
    rc.round_trip(edit=lambda: append_commit(rc.repo, UTIL, "# second"))
    rc.round_trip(edit=lambda: append_commit(rc.repo, UTIL, "# third"))


def test_round_four_asks_whether_to_reconsider_the_approach(rc: Rc) -> None:
    """RND-14, CLI-9 round-4 row, CLI-11."""
    three_rounds_with_a_surviving_finding(rc)
    append_commit(rc.repo, UTIL, "# fourth")
    out = rc.cli("high", "--full")
    sd = rc.state_dir()
    assert out.code == 0
    assert out.keys == ["state", "next", "question", "options", "on-continue"]
    assert Path(out.get("state")).resolve() == sd.resolve()
    assert out.get("next") == "ask"
    assert out.get("question") == (
        "Open Important findings survived a fix round (F1). Reconsider the approach?"
    )
    assert out.get("options") == "reconsider | continue"
    assert out.get("on-continue") == (
        f"review-cycle-state continue --data-dir {rc.data_dir} --state-dir {out.get('state')}"
    )
    assert rc.plan_json()["status"] == "awaiting_confirmation"
    stale = rc.merge(build_result(rc.plan_json()))
    assert stale.code == 1
    assert "plan is not ready (status awaiting_confirmation)" in stale.get("error")


def test_round_four_question_repeats_until_the_user_continues(rc: Rc) -> None:
    """RND-14/CLI-11: asked before every round while true; `continue` proceeds."""
    three_rounds_with_a_surviving_finding(rc)
    append_commit(rc.repo, UTIL, "# fourth")
    assert rc.cli("high", "--full").get("next") == "ask"
    assert rc.cli("high", "--full").get("next") == "ask"
    go = rc.cont()
    assert go.code == 0 and go.get("next") == "workflow"
    assert go.get("round").startswith("4 · ")
    assert go.has("workflow-args") and go.has("base")
    assert rc.plan_json()["status"] == "ready"
    again = rc.cont()
    assert again.code == 1 and again.get("next") == "stop"
    rc.merge(build_result(rc.plan_json()))
    append_commit(rc.repo, UTIL, "# fifth")
    assert rc.cli("high", "--full").get("next") == "ask"


def test_continue_without_a_pending_question_is_refused(rc: Rc) -> None:
    """CLI-11: only `awaiting_confirmation` plans can be continued."""
    seed_branch(rc.repo)
    rc.cli("high")
    out = rc.cont()
    assert out.code == 1 and out.get("next") == "stop"


def test_state_json_keeps_the_round_bookkeeping(rc: Rc) -> None:
    """ST-4, ST-6: what later rounds depend on."""
    seed_branch(rc.repo)
    plan, _ = rc.round_trip(candidates=[C_APP])
    state = rc.state_json()
    assert state["round"] == 1 and state["last_plan_id"] == plan["plan_id"]
    assert state["change_id"] == plan["change_id"] and state["file_ids"] == plan["file_ids"]
    assert state["base_ref"] == "main" and state["tree_sha"] == plan["tree_sha"]
    entry = state["rounds"][0]
    assert entry["n"] == 1 and entry["plan_id"] == plan["plan_id"]
    assert entry["scope_kind"] == "full" and entry["candidates"] == 1 and entry["kept"] == 1
    assert rc.plan_json()["status"] == "merged"
    assert isinstance(entry["held_back"], dict) and "lost_votes" in entry
    assert re.fullmatch(r"[0-9a-f]{40}", entry["head_sha"])
    assert (rc.state_dir() / "round-1.md").exists()


def test_round_three_with_only_deleted_files(rc: Rc) -> None:
    """RND-9: the only change is a file leaving the branch diff."""
    seed_branch(rc.repo)
    rc.round_trip()
    rc.round_trip(edit=lambda: append_commit(rc.repo, UTIL, "# second"))
    rc.repo.run("rm", "-q", NEW)
    rc.repo.run("commit", "-q", "-m", "drop new.py")
    out = rc.cli("high", "--incremental")
    assert out.get("next") == "workflow"
    scope = rc.plan_json()["scope"]
    assert scope["kind"] == "since" and scope["files"] == [] and scope["deleted"] == [NEW]


def test_on_continue_quotes_a_data_dir_with_spaces_and_quotes(rc: Rc, tmp_path: Path) -> None:
    """RND-14/CLI-9: the printed command is shell-safe."""
    import shlex

    rc.data_dir = tmp_path / "my data's dir"
    rc.data_dir.mkdir()
    three_rounds_with_a_surviving_finding(rc)
    append_commit(rc.repo, UTIL, "# fourth")
    out = rc.cli("high", "--full")
    assert out.get("on-continue") == (
        f"review-cycle-state continue --data-dir {shlex.quote(str(rc.data_dir))} "
        f"--state-dir {shlex.quote(out.get('state'))}"
    )
