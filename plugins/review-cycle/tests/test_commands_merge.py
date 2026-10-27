"""`merge`: accepted results, rejected results leave the state untouched (CLI-9..CLI-12, ST-12)."""

from __future__ import annotations

import json
import os
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from conftest import GitRepo
from helpers_git import APP, Rc, app_text, append_commit, make_rc, seed_branch, tree_bytes
from helpers_result import (
    PROVENANCE,
    build_result,
    cand,
    runtime_wrapped,
    with_bad_checksum,
    without_first_verdict,
)

C_APP = cand()
C_DIV = cand(
    path="src/util.py",
    line=2,
    symbol="f",
    snippet="    x = a / b",
    claim="divides by zero",
    cls="div",
)
FINDING_KEYS = {
    "file", "line", "summary", "failure_scenario", "category", "short_summary", "verdict",
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


def test_merge_prints_the_report_and_report_findings(rc: Rc) -> None:
    """CLI-9 (merge ok), RPT-1, RPT-2, RPT-8."""
    seed_branch(rc.repo, util_findings=True)
    _, out = rc.round_trip(candidates=[C_APP, C_DIV])
    assert out.get("next") == "print-report"
    assert out.report.splitlines()[0].startswith("review-cycle · round 1 · high · vs main@")
    assert (
        "0 needs your decision · 2 agent can fix · 0 Nit · 0 Pre-existing · 0 rejected"
        in out.report
    )
    assert "Agent can fix" in out.report and "F1" in out.report and "F2" in out.report
    (line,) = out.findings_lines()
    assert line["level"] == "high"
    assert [set(f) for f in line["findings"]] == [FINDING_KEYS, FINDING_KEYS]
    first = line["findings"][0]
    assert first["file"] == "src/app.py" and first["line"] == 21
    assert first["summary"] == C_APP["claim"] and first["failure_scenario"] == C_APP["trigger"]
    assert first["short_summary"] == "unchecked call" and first["verdict"] == "CONFIRMED"


def test_merge_without_findings_says_nothing_to_fix(rc: Rc) -> None:
    """RPT-3, CLI-9: k = 0 `report-findings:` lines."""
    seed_branch(rc.repo)
    _, out = rc.round_trip()
    assert "Nothing to fix." in out.report
    assert out.all("report-findings") == []


def test_report_findings_are_chunked_at_thirty_two(rc: Rc) -> None:
    """RPT-8."""
    seed_branch(rc.repo)
    many = [
        cand(snippet=f"    risky_{i}(x)", symbol=f"h{i}", claim=f"problem {i}") for i in range(33)
    ]
    _, out = rc.round_trip(candidates=many)
    sizes = [len(x["findings"]) for x in out.findings_lines()]
    assert sizes == [32, 1]


def test_merge_writes_state_plan_and_round_file(rc: Rc) -> None:
    """ST-4, ST-5, ST-6, RPT-7, NFR-2: files written by `merge`."""
    seed_branch(rc.repo, util_findings=True)
    plan, _ = rc.round_trip(candidates=[C_APP])
    state = rc.state_json()
    assert state["round"] == 1 and state["last_plan_id"] == plan["plan_id"]
    (finding,) = state["findings"]
    assert finding["id"] == "F1" and finding["status"] == "open"
    assert finding["severity"] == "important" and finding["origin"] == "introduced"
    assert finding["first_round"] == finding["last_seen_round"] == 1
    assert finding["anchor"]["path"] == "src/app.py" and finding["anchor"]["line"] == 21
    assert rc.plan_json()["status"] == "merged"
    text = (rc.state_dir() / "round-1.md").read_text(encoding="utf-8")
    assert "## Hand-off for the coding flow" in text
    assert "### F1 · unchecked call" in text
    assert "Problem: " + C_APP["claim"] in text


def test_merging_the_same_result_twice_prints_the_report_again(rc: Rc) -> None:
    """CLI-9/CLI-10: already merged -> exit 0, state untouched."""
    seed_branch(rc.repo)
    rc.cli("high")
    result = build_result(rc.plan_json(), [C_APP])
    assert rc.merge(result).code == 0
    before = tree_bytes(rc.state_dir())
    again = rc.merge(result)
    assert again.code == 0 and again.get("next") == "print-report"
    assert "F1" in again.report
    assert tree_bytes(rc.state_dir()) == before


def test_merge_accepts_the_runtime_output_file_shape(rc: Rc) -> None:
    """CLI-12: `{result: {...}}` without `provenance` is unwrapped."""
    seed_branch(rc.repo)
    rc.cli("high")
    wrapped = runtime_wrapped(build_result(rc.plan_json(), [C_APP]))
    assert "provenance" not in wrapped
    out = rc.merge(wrapped)
    assert out.code == 0, out.err
    assert [f["id"] for f in rc.state_json()["findings"]] == ["F1"]


def test_merge_accepts_the_bare_result(rc: Rc) -> None:
    """CLI-12: a session-written copy is used as is."""
    seed_branch(rc.repo)
    rc.cli("high")
    bare = build_result(rc.plan_json(), [C_APP])
    assert bare["provenance"] == PROVENANCE
    assert rc.merge(bare).code == 0


def broken_stale(rc: Rc) -> tuple[Any, str]:
    old = build_result(rc.plan_json())
    old_id = rc.plan_json()["plan_id"]
    rc.cli("high", "--full")
    new_id = rc.plan_json()["plan_id"]
    return old, f"result is for plan {old_id}, current plan is {new_id}"


def broken_checksum(rc: Rc) -> tuple[Any, str]:
    return with_bad_checksum(build_result(rc.plan_json(), [C_APP])), "result checksum mismatch"


def broken_coverage(rc: Rc) -> tuple[Any, str]:
    result = without_first_verdict(build_result(rc.plan_json(), [C_APP]))
    return result, "verdict coverage incomplete: N1.1/vote/0"


def broken_not_started(rc: Rc) -> tuple[Any, str]:
    result = {"provenance": PROVENANCE, "v": 1, "started": False, "reason": "no-args", "next": "x"}
    return result, "workflow did not start: no-args"


def broken_not_object(rc: Rc) -> tuple[Any, str]:
    return [1, 2], "result is not a JSON object"


@pytest.mark.parametrize(
    "broken",
    [broken_stale, broken_checksum, broken_coverage, broken_not_started, broken_not_object],
)
def test_rejected_results_leave_everything_untouched(
    rc: Rc, broken: Callable[[Rc], tuple[Any, str]]
) -> None:
    """ST-12, ST-13, §12: validation completes before the first write (state exists)."""
    seed_branch(rc.repo)
    rc.round_trip(candidates=[C_APP])
    append_commit(rc.repo, "src/util.py", "# edit")
    assert rc.cli("high", "--full").get("next") == "workflow"
    payload, message = broken(rc)
    before = tree_bytes(rc.state_dir())
    outcomes_before = rc.outcomes()
    out = rc.merge(payload) if isinstance(payload, dict) else rc.merge_file(write(rc, payload))
    assert out.code == 1
    assert out.get("next") == "stop"
    assert out.get("error") == message
    assert f"error: {message}" in out.err.splitlines()
    assert tree_bytes(rc.state_dir()) == before
    assert rc.outcomes() == outcomes_before


def write(rc: Rc, payload: object) -> Path:
    path = rc.tmp / "odd-result.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_unreadable_result_files(rc: Rc) -> None:
    """ST-13 (file read/parse)."""
    seed_branch(rc.repo)
    rc.cli("high")
    before = tree_bytes(rc.state_dir())
    missing = rc.merge_file(rc.tmp / "nope.json")
    assert missing.code == 1 and missing.get("error").startswith("result file unreadable: ")
    garbled = rc.tmp / "garbled.json"
    garbled.write_text("{not json", encoding="utf-8")
    bad = rc.merge_file(garbled)
    assert bad.code == 1 and bad.get("error").startswith("result file unreadable: ")
    assert tree_bytes(rc.state_dir()) == before


def test_rule_suggestion_after_repeated_wrong_marks_in_the_repo(rc: Rc, data_dir: Path) -> None:
    """FND-16 (run in merge): 3 `wrong` outcomes of one class in this repo -> one suggestion."""
    seed_branch(rc.repo)
    lines = [
        {
            "ts": "2026-10-01T00:00:00Z", "repo": str(rc.root), "branch": "feature/old",
            "mode": "code", "level": "high", "finding_id": f"F{i}", "category": "logic",
            "class": "unchecked call", "severity": "important", "status": "wrong",
            "response_type": "agent_can_fix", "round": 1, "first_round": 1,
            "moved_from_decision": False,
        }
        for i in range(1, 4)
    ]  # fmt: skip
    (data_dir / "outcomes.jsonl").write_text(
        "".join(json.dumps(x) + "\n" for x in lines), encoding="utf-8"
    )
    _, out = rc.round_trip()
    assert 'Rule suggestion: "unchecked call" marked wrong 3× in this repo.' in out.report
    assert rc.state_json()["suggested_rules"] == ["unchecked call"]
    append_commit(rc.repo, "src/util.py", "# edit")
    _, again = rc.round_trip()
    assert "Rule suggestion" not in again.report


def test_writes_go_through_tmp_file_and_replace(rc: Rc, monkeypatch: pytest.MonkeyPatch) -> None:
    """NFR-2: plan.json, state.json, round-N.md and last-level are replaced atomically."""
    seed_branch(rc.repo)
    calls: list[tuple[str, str]] = []
    real_replace = os.replace

    def spy(src: Any, dst: Any) -> None:
        calls.append((str(src), str(dst)))
        real_replace(src, dst)

    monkeypatch.setattr(os, "replace", spy)
    rc.round_trip(tokens=["high"], candidates=[C_APP])
    written = {os.path.basename(dst) for _, dst in calls}
    assert {"plan.json", "state.json", "round-1.md", "last-level"} <= written
    for src, dst in calls:
        assert os.path.dirname(src) == os.path.dirname(dst)
        assert src != dst


def test_a_failing_write_does_not_leave_a_state_file(
    rc: Rc, monkeypatch: pytest.MonkeyPatch
) -> None:
    """NFR-2/§12: an error while writing exits 1 and never leaves a truncated state.json."""
    seed_branch(rc.repo)
    rc.cli("high")
    result = build_result(rc.plan_json(), [C_APP])
    real_replace = os.replace

    def fail_state(src: Any, dst: Any) -> None:
        if os.path.basename(str(dst)) == "state.json":
            raise OSError("disk full")
        real_replace(src, dst)

    monkeypatch.setattr(os, "replace", fail_state)
    out = rc.merge(result)
    assert out.code == 1
    assert out.get("error").startswith("internal: OSError")
    assert not (rc.state_dir() / "state.json").exists()


@pytest.mark.parametrize("damage", [with_bad_checksum, without_first_verdict])
def test_same_plan_id_prints_the_stored_report_without_validation(
    rc: Rc, damage: Callable[[Any], dict[str, Any]]
) -> None:
    """ST-12/RPT-12: plan_id == state.last_plan_id -> stored report, exit 0, no write."""
    seed_branch(rc.repo)
    rc.cli("high")
    result = build_result(rc.plan_json(), [C_APP])
    assert rc.merge(result).code == 0
    before = tree_bytes(rc.state_dir())
    again = rc.merge(damage(result))
    assert again.code == 0 and again.get("next") == "print-report"
    assert "F1" in again.report
    assert tree_bytes(rc.state_dir()) == before


def test_outcomes_are_appended_before_state_json_is_committed(
    rc: Rc, monkeypatch: pytest.MonkeyPatch
) -> None:
    """RPT-15: a crash while writing state.json may duplicate outcome lines, never lose them."""
    seed_branch(rc.repo)
    rc.round_trip(candidates=[C_APP])
    rc.repo.commit({APP: app_text()}, "remove the risky line")
    rc.cli("high", "--full")
    result = build_result(rc.plan_json(), recheck={"F1": [False, False]})
    real_replace = os.replace

    def fail_state(src: Any, dst: Any) -> None:
        if os.path.basename(str(dst)) == "state.json":
            raise OSError("disk full")
        real_replace(src, dst)

    monkeypatch.setattr(os, "replace", fail_state)
    assert rc.merge(result).code == 1
    assert [o["status"] for o in rc.outcomes()] == ["fixed"]
    assert rc.state_json()["round"] == 1


def test_corrupt_state_json_names_the_file(rc: Rc) -> None:
    """RPT-15: exit 1 naming the path, no traceback-only failure."""
    seed_branch(rc.repo)
    rc.round_trip(candidates=[C_APP])
    path = rc.state_dir() / "state.json"
    path.write_text("{broken", encoding="utf-8")
    append_commit(rc.repo, "src/util.py", "# edit")
    out = rc.cli()
    assert out.code == 1 and out.get("next") == "stop"
    assert str(path) in out.get("error")
