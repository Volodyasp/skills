"""`mark` and `show` (CLI-2, CLI-3, CLI-8, FND-15, FND-16) and the outcomes log (ST-7)."""

from __future__ import annotations

import json
import os
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from conftest import GitRepo
from helpers_git import APP, UTIL, Out, Rc, app_text, make_rc, seed_branch, tree_bytes
from helpers_result import build_result, cand

C_APP = cand()
C_DIV = cand(
    path=UTIL, line=2, symbol="f", snippet="    x = a / b", claim="divides by zero", cls="div"
)
OUTCOME_KEYS = {
    "ts", "repo", "branch", "mode", "level", "finding_id", "category", "class", "severity",
    "status", "response_type", "round", "first_round", "moved_from_decision",
}  # fmt: skip
C1_DECISION = {
    "criterion": 1,
    "before": "a refund returns the full sum",
    "after": "a refund returns the paid sum",
    "intent_quote": "",
    "options": [],
}


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


def two_findings(rc: Rc) -> None:
    seed_branch(rc.repo, util_findings=True)
    rc.round_trip(candidates=[C_APP, C_DIV])


def finding(rc: Rc, fid: str, target: str = "code") -> dict[str, Any]:
    return next(f for f in rc.state_json(target)["findings"] if f["id"] == fid)


@pytest.mark.parametrize("verb", ["intentional", "wontfix", "wrong", "superseded"])
def test_decisions_set_status_disposition_and_outcome(rc: Rc, verb: str) -> None:
    """CLI-2, FND-15 (open x decide), ST-7."""
    two_findings(rc)
    out = rc.cli("F1", verb, "because it is so")
    assert out.code == 0, out.err
    assert out.get("marked") == f"F1 {verb}"
    f = finding(rc, "F1")
    assert f["status"] == verb
    assert f["disposition"]["reason"] == "because it is so"
    assert f["disposition"]["at"] and f["disposition"]["snippet_hash"]
    assert f["response_type"] == "agent_can_fix"
    (line,) = rc.outcomes()
    assert line["finding_id"] == "F1" and line["status"] == verb
    assert line["response_type"] == "agent_can_fix" and line["round"] == 1
    assert line["first_round"] == 1 and line["moved_from_decision"] is False
    assert line["severity"] == "important" and line["mode"] == "code"
    assert line["branch"] == "feature/seed" and line["level"] == "high"


def test_reason_is_the_remaining_tokens_joined_by_one_space(rc: Rc) -> None:
    """CLI-2."""
    two_findings(rc)
    rc.cli("F2", "wontfix", "later,", "not", "now")
    assert finding(rc, "F2")["disposition"]["reason"] == "later, not now"


def test_wrong_without_a_reason_is_a_usage_error_and_changes_nothing(rc: Rc) -> None:
    """CLI-2/CLI-10: exit 2."""
    two_findings(rc)
    before = tree_bytes(rc.state_dir())
    assert rc.cli("F1", "wrong").code == 2
    assert tree_bytes(rc.state_dir()) == before
    assert rc.outcomes() == []


def test_open_on_an_open_finding_is_a_no_op(rc: Rc) -> None:
    """FND-15 (open x open): exit 0, message, no outcome line."""
    two_findings(rc)
    out = rc.cli("F1", "open")
    assert out.code == 0 and "F1 is already open" in out.out
    assert rc.outcomes() == []


def test_open_reopens_a_decided_finding(rc: Rc) -> None:
    """FND-15 (decided x open)."""
    two_findings(rc)
    rc.cli("F1", "intentional", "x")
    out = rc.cli("F1", "open")
    f = finding(rc, "F1")
    assert out.code == 0 and f["status"] == "open"
    assert f["disposition"] is None and f["reopen_round"] is None


def test_a_decided_finding_can_be_decided_again(rc: Rc) -> None:
    """FND-15 (decided x decide): replaced status and reason, one outcome line per decision."""
    two_findings(rc)
    rc.cli("F1", "intentional", "first")
    out = rc.cli("F1", "wontfix", "second")
    assert out.code == 0
    f = finding(rc, "F1")
    assert (f["status"], f["disposition"]["reason"]) == ("wontfix", "second")
    assert [o["status"] for o in rc.outcomes()] == ["intentional", "wontfix"]


def test_fix_on_a_finding_that_needs_no_decision_is_refused(rc: Rc) -> None:
    """FND-15 (open x fix, none)."""
    two_findings(rc)
    out = rc.cli("F1", "fix")
    assert out.code == 1
    assert out.get("error") == 'F1 is not in "needs your decision"'


def test_fix_moves_a_finding_out_of_needs_your_decision(rc: Rc) -> None:
    """FND-15 (open x fix, has needs_decision), FND-14."""
    seed_branch(rc.repo)
    _, merged = rc.round_trip(candidates=[C_APP], decisions={"N1.1": C1_DECISION})
    assert "Needs your decision" in merged.report
    assert finding(rc, "F1")["needs_decision"]["criterion"] == 1
    out = rc.cli("F1", "fix")
    f = finding(rc, "F1")
    assert out.code == 0
    assert f["needs_decision"] is None and f["moved_from_decision"] is True
    report = rc.cli().report
    assert "Needs your decision" not in report and "Agent can fix" in report
    assert rc.outcomes() == []


def test_unknown_finding_id(rc: Rc) -> None:
    """CLI-8."""
    two_findings(rc)
    for tokens in (["F9", "intentional", "x"], ["show", "F9"]):
        out = rc.cli(*tokens)
        assert out.code == 1 and out.get("next") == "stop"
        assert out.get("error") == "no finding F9"


def test_findings_of_another_branch_are_not_found(rc: Rc) -> None:
    """CLI-8: only the current branch's state directories are searched."""
    two_findings(rc)
    rc.repo.branch("other")
    out = rc.cli("F1", "wontfix", "x")
    assert out.code == 1 and out.get("error") == "no finding F1"


def test_ambiguous_finding_id_lists_the_targets(rc: Rc) -> None:
    """CLI-8/RPT-20(d): the same id in a code state and a document state -> exit 1, both listed,
    each qualified, sorted, with the exact collision message."""
    two_findings(rc)
    rc.repo.commit({"docs/spec.md": "# Spec\n\n## Goal\ntext\n"}, "add doc")
    rc.cli("docs/spec.md", "high")
    doc_candidate = cand(
        path="docs/spec.md", line=3, symbol="Spec > Goal", snippet="text", category="gap"
    )
    rc.merge(build_result(rc.plan_json("doc-docs-spec-md"), [doc_candidate]), "doc-docs-spec-md")
    expected = (
        "F1 exists in several review targets: code/F1, doc-docs-spec-md/F1; repeat with one of them"
    )
    for tokens in (["F1", "intentional", "x"], ["show", "F1"]):
        out = rc.cli(*tokens)
        assert out.code == 1
        assert out.get("error") == expected


def test_qualified_mark_and_show_bypass_the_collision_check(rc: Rc) -> None:
    """RPT-20(d): a qualified `<target>/F<n>` id looks only in that one target."""
    two_findings(rc)
    rc.repo.commit({"docs/spec.md": "# Spec\n\n## Goal\ntext\n"}, "add doc")
    rc.cli("docs/spec.md", "high")
    doc_candidate = cand(
        path="docs/spec.md", line=3, symbol="Spec > Goal", snippet="text", category="gap"
    )
    rc.merge(build_result(rc.plan_json("doc-docs-spec-md"), [doc_candidate]), "doc-docs-spec-md")
    marked = rc.cli("code/F1", "wontfix", "code side")
    assert marked.code == 0 and marked.get("marked") == "F1 wontfix"
    assert finding(rc, "F1", "code")["status"] == "wontfix"
    assert finding(rc, "F1", "doc-docs-spec-md")["status"] == "open"
    shown = rc.cli("show", "doc-docs-spec-md/F1")
    assert shown.code == 0 and shown.get("next") == "print-report"
    assert "F1" in shown.report


def test_qualified_mark_with_an_unknown_target_is_an_error(rc: Rc) -> None:
    """RPT-20(d): a qualified id for a nonexistent or wrong target -> `no finding <target>/F<n>`."""
    two_findings(rc)
    out = rc.cli("doc-nope/F1", "wontfix", "x")
    assert out.code == 1 and out.get("error") == "no finding doc-nope/F1"
    wrong_target = rc.cli("show", "code/F999")
    assert wrong_target.code == 1 and wrong_target.get("error") == "no finding code/F999"


def test_show_prints_the_finding_details(rc: Rc) -> None:
    """CLI-3, CLI-9 (show), RPT-9."""
    two_findings(rc)
    out = rc.cli("show", "F1")
    assert out.code == 0 and out.get("next") == "print-report"
    assert "F1" in out.report and C_APP["claim"] in out.report
    assert C_APP["evidence"] in out.report and "src/app.py" in out.report


def candidates_of_one_class(n: int) -> list[dict[str, Any]]:
    return [
        cand(snippet=f"    risky_{i}(x)", symbol=f"h{i}", claim=f"problem {i}") for i in range(n)
    ]


def test_rule_suggestion_after_the_third_wrong_of_one_class(rc: Rc) -> None:
    """FND-16, CLI-9 (mark ok): suggested once, recorded in the state."""
    seed_branch(rc.repo)
    rc.round_trip(candidates=candidates_of_one_class(4))
    first = rc.cli("F1", "wrong", "it is guarded upstream")
    second = rc.cli("F2", "wrong", "guarded upstream too")
    third = rc.cli("F3", "wrong", "guarded elsewhere")
    assert not first.has("rule-suggestion") and not second.has("rule-suggestion")
    text = third.get("rule-suggestion")
    assert text == (
        'Rule suggestion: "unchecked call" marked wrong 3× in this repo. '
        "A REVIEW.md line such as: Do not report unchecked call."
    )
    assert "guarded" not in text
    assert rc.state_json()["suggested_rules"] == ["unchecked call"]
    assert not rc.cli("F4", "wrong", "same again").has("rule-suggestion")


def sentinel_round(rc: Rc) -> dict[str, Any]:
    """Round with a long class and sentinel texts in every free-text field."""
    seed_branch(rc.repo)
    item = cand(
        cls="C" * 200,
        claim="CLAIM-SENTINEL",
        evidence="EVIDENCE-SENTINEL",
        snippet="    return risky(x)  # SNIPPET-SENTINEL",
        trigger="TRIGGER-SENTINEL",
    )
    rc.round_trip(candidates=[item])
    rc.cli("F1", "wrong", "REASON-SENTINEL")
    return item


def test_outcomes_carry_no_code_or_free_text(rc: Rc, data_dir: Path) -> None:
    """ST-7/§13: exact key set, class cut to 80 characters, no claim/snippet/evidence/reason."""
    sentinel_round(rc)
    raw = (data_dir / "outcomes.jsonl").read_text(encoding="utf-8")
    for word in ("CLAIM-SENTINEL", "EVIDENCE-SENTINEL", "SNIPPET-SENTINEL", "REASON-SENTINEL"):
        assert word not in raw
    (line,) = rc.outcomes()
    assert set(line) == OUTCOME_KEYS
    assert 0 < len(line["class"]) <= 80


def test_outcome_repo_is_the_toplevel_without_a_remote(rc: Rc) -> None:
    """ST-7: no origin -> absolute toplevel."""
    two_findings(rc)
    rc.cli("F1", "wontfix", "x")
    assert rc.outcomes()[0]["repo"] == str(rc.root)


def test_outcome_repo_drops_credentials_from_the_origin_url(rc: Rc) -> None:
    """ST-7/§13: `https://u:tok@host/o/r.git` -> `https://host/o/r.git`."""
    rc.repo.run("remote", "add", "origin", "https://u:tok@example.com/o/r.git")
    two_findings(rc)
    rc.cli("F1", "wontfix", "x")
    (line,) = rc.outcomes()
    assert line["repo"] == "https://example.com/o/r.git"
    assert "tok" not in json.dumps(line)


def test_outcome_repo_keeps_scp_style_origin(rc: Rc) -> None:
    """ST-7."""
    rc.repo.run("remote", "add", "origin", "git@github.com:o/r.git")
    two_findings(rc)
    rc.cli("F1", "wontfix", "x")
    assert rc.outcomes()[0]["repo"] == "git@github.com:o/r.git"


def test_mark_output_shape(rc: Rc) -> None:
    """CLI-9 (mark ok): machine line `marked: F<n> <verb>`."""
    two_findings(rc)
    out: Out = rc.cli("F2", "superseded", "replaced by F1")
    assert out.keys[0] == "marked" and out.get("marked") == "F2 superseded"


def fixed_finding(rc: Rc) -> None:
    """Round 1 finds F1; the seeded line is removed; round 2 re-check closes it."""
    seed_branch(rc.repo)
    rc.round_trip(candidates=[C_APP])
    rc.repo.commit({APP: app_text()}, "remove the risky line")
    rc.cli("high", "--full")
    rc.merge(build_result(rc.plan_json(), recheck={"F1": [False, False]}))
    assert finding(rc, "F1")["status"] == "fixed"


def test_open_reopens_a_fixed_finding(rc: Rc) -> None:
    """FND-15 (fixed x open)."""
    fixed_finding(rc)
    out = rc.cli("F1", "open")
    f = finding(rc, "F1")
    assert out.code == 0 and f["status"] == "open" and f["reopen_round"] is None


def test_fix_on_a_fixed_finding_is_refused(rc: Rc) -> None:
    """FND-15 (fixed x fix)."""
    fixed_finding(rc)
    out = rc.cli("F1", "fix")
    assert out.code == 1 and out.get("error") == "F1 is fixed, not open"


def test_deciding_a_fixed_finding_records_response_type_fixed(rc: Rc) -> None:
    """FND-15 (fixed x decide), ST-7."""
    fixed_finding(rc)
    assert rc.cli("F1", "wontfix", "late").code == 0
    assert finding(rc, "F1")["status"] == "wontfix"
    assert rc.outcomes()[-1]["response_type"] == "fixed"


def test_fix_on_a_decided_finding_is_refused(rc: Rc) -> None:
    """FND-15 (decided x fix)."""
    two_findings(rc)
    rc.cli("F1", "intentional", "x")
    out = rc.cli("F1", "fix")
    assert out.code == 1 and out.get("error") == "F1 is intentional, not open"


@pytest.mark.parametrize("tokens", [["F1", "wontfix", "x"], ["show", "F1"]])
def test_mark_and_show_refuse_a_detached_head(rc: Rc, tokens: list[str]) -> None:
    """CLI-7 (RPT-12): detached HEAD -> exit 1."""
    two_findings(rc)
    rc.repo.run("checkout", "-q", "--detach")
    out = rc.cli(*tokens)
    assert out.code == 1 and out.get("error") == "detached HEAD; check out a branch"


def test_only_the_current_branch_dir_is_searched_when_two_exist(rc: Rc) -> None:
    """CLI-8: the same id on two branches never clashes."""
    seed_branch(rc.repo)
    rc.round_trip(candidates=[C_APP])
    rc.repo.branch("feature/two")
    rc.round_trip(candidates=[C_APP])
    out = rc.cli("F1", "wontfix", "only here")
    assert out.code == 0
    assert finding(rc, "F1")["status"] == "wontfix"
    other = json.loads((rc.state_dir("feature/seed") / "state.json").read_text(encoding="utf-8"))
    assert other["findings"][0]["status"] == "open"


def test_mark_appends_the_outcome_before_committing_state(
    rc: Rc, monkeypatch: pytest.MonkeyPatch
) -> None:
    """RPT-15."""
    two_findings(rc)
    real_replace = os.replace

    def fail_state(src: Any, dst: Any) -> None:
        if os.path.basename(str(dst)) == "state.json":
            raise OSError("disk full")
        real_replace(src, dst)

    monkeypatch.setattr(os, "replace", fail_state)
    assert rc.cli("F1", "wontfix", "x").code == 1
    assert [o["finding_id"] for o in rc.outcomes()] == ["F1"]
    assert finding(rc, "F1")["status"] == "open"


def test_a_state_dir_of_another_branch_is_not_searched(rc: Rc) -> None:
    """RPT-15: only state dirs whose `branch` is the current branch count."""
    two_findings(rc)
    state = rc.state_json()
    state["branch"] = "someone/else"
    rc.write_state(state)
    for tokens in (["F1", "wontfix", "x"], ["show", "F1"]):
        out = rc.cli(*tokens)
        assert out.code == 1 and out.get("error") == "no finding F1"
