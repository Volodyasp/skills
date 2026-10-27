"""Document-mode rounds (DOC-1..DOC-5, RND-16 doc rule, CLI-7)."""

from __future__ import annotations

import hashlib
import re
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from conftest import GitRepo
from helpers_git import Rc, assert_error, make_rc
from helpers_result import build_result, cand
from review_cycle import docmode
from review_cycle.levels import LEVELS

DOC = "docs/spec.md"
TARGET = "doc-docs-spec-md"
TEXT = "# Spec\n\n## Goal\ngoal text\n\n## Scope\nscope text\n\n## Risks\nrisk text\n"
SECTIONS = ["Spec", "Spec > Goal", "Spec > Scope", "Spec > Risks"]


def doc_cand(heading: str, **over: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "path": DOC,
        "line": 5,
        "symbol": heading,
        "snippet": "scope text",
        "claim": "the scope never says what is excluded",
        "category": "gap",
        "cls": "missing exclusion",
    }
    return cand(**{**base, **over})


@pytest.fixture
def rc(
    git_repo: GitRepo,
    data_dir: Path,
    run_cli: Callable[[list[str], Path], tuple[int, str, str]],
    fake_gh_dir: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> Rc:
    rc = make_rc(git_repo, data_dir, run_cli, fake_gh_dir, tmp_path, monkeypatch)
    rc.repo.branch("feature/doc")
    return rc


def doc_round(rc: Rc, *candidates: dict[str, Any], tokens: tuple[str, ...] = ()) -> None:
    """Plan and merge a document round; fills in `high`/`--full` like `Rc.round_trip` (RPT-18)."""
    full_tokens = list(tokens)
    if not any(t in LEVELS for t in full_tokens):
        full_tokens = ["high", *full_tokens]
    has_state = (rc.state_dir(target=TARGET) / "state.json").exists()
    if has_state and not any(t in ("--full", "--incremental", "--fresh") for t in full_tokens):
        full_tokens.append("--full")
    out = rc.cli(DOC, *full_tokens)
    assert out.get("next") == "workflow", out.out
    merged = rc.merge(build_result(rc.plan_json(TARGET), candidates), TARGET)
    assert merged.code == 0, merged.err


def test_untracked_document_plan(rc: Rc) -> None:
    """DOC-1, DOC-3, DOC-4, CLI-9, ST-1: an untracked doc is reviewed by content."""
    rc.repo.write(DOC, TEXT)
    out = rc.cli(DOC, "high")
    assert out.code == 0, out.err
    assert "base" not in out.keys and "small-diff" not in out.keys
    assert rc.plan_json(TARGET)["small_diff"]["applied"] is False
    assert len(rc.plan_json(TARGET)["level_config"]["finders"]) == 4
    assert out.keys[0] == "state" and out.get("next") == "workflow"
    assert Path(out.get("state")).resolve() == rc.state_dir(target=TARGET).resolve()
    assert "document" in out.get("round")
    plan = rc.plan_json(TARGET)
    digest = hashlib.sha256(TEXT.encode("utf-8")).hexdigest()
    assert plan["mode"] == "document" and plan["target"] == TARGET
    assert plan["doc_sha256"] == digest and plan["change_id"] == digest
    assert plan["tree_sha"] is None and plan["round"] == 1
    assert plan["scope"]["kind"] == "full" and plan["scope"]["sections"] == SECTIONS
    args = plan["workflow"]["args"]
    assert args["mode"] == "document" and args["lens_file"].endswith("references/document.md")
    assert [f["lens"] for f in plan["level_config"]["finders"]] == [
        "contradictions-gaps",
        "code-claims",
        "ambiguity",
        "unneeded",
    ]


def test_tracked_and_untracked_copies_have_the_same_change_id(rc: Rc) -> None:
    """DOC-3."""
    rc.repo.write(DOC, TEXT)
    rc.cli(DOC, "high")
    untracked = rc.plan_json(TARGET)["change_id"]
    rc.repo.commit({}, "track it")
    rc.cli(DOC, "high")
    assert rc.plan_json(TARGET)["change_id"] == untracked


def test_document_outside_the_repository_is_refused(rc: Rc, tmp_path: Path) -> None:
    """DOC-1."""
    outside = tmp_path / "outside.md"
    outside.write_text(TEXT, encoding="utf-8")
    out = rc.cli(str(outside))
    assert out.code == 1 and out.get("next") == "stop"


def test_document_mode_refuses_a_detached_head(rc: Rc) -> None:
    """CLI-7 (any mode)."""
    rc.repo.write(DOC, TEXT)
    rc.repo.commit({}, "doc")
    rc.repo.run("checkout", "-q", "--detach")
    assert_error(rc.cli(DOC), 1, "detached HEAD; check out a branch")


def test_merge_stores_the_snapshot_and_section_hashes(rc: Rc) -> None:
    """DOC-3: `doc-snapshot.md` and `state.sections`."""
    rc.repo.write(DOC, TEXT)
    doc_round(rc)
    assert (rc.state_dir(target=TARGET) / "doc-snapshot.md").read_text("utf-8") == TEXT
    state = rc.state_json(TARGET)
    assert state["sections"] == docmode.section_hashes(TEXT)
    assert (
        state["mode"] == "document"
        and state["change_id"] == hashlib.sha256(TEXT.encode("utf-8")).hexdigest()
    )


def test_unchanged_document_prints_the_previous_report(rc: Rc) -> None:
    """RND-7 for documents, RPT-1."""
    rc.repo.write(DOC, TEXT)
    doc_round(rc, doc_cand("Spec > Scope"))
    out = rc.cli(DOC)
    assert out.get("next") == "print-report"
    assert out.report.startswith("No code change since round 1 — not a new round.")


def test_scope_in_round_three_is_the_changed_sections(rc: Rc) -> None:
    """DOC-4: rounds 1-2 are the whole document; round 3 only changed or new sections."""
    rc.repo.write(DOC, TEXT)
    doc_round(rc)
    second = TEXT.replace("risk text", "risk text, edited")
    rc.repo.write(DOC, second)
    doc_round(rc)
    assert rc.plan_json(TARGET)["scope"]["sections"] == SECTIONS
    third = second.replace("goal text", "goal text, edited") + "\n## Extra\nnew\n"
    rc.repo.write(DOC, third)
    out = rc.cli(DOC, "high", "--incremental")
    assert out.get("round").startswith("3 · ")
    assert sorted(rc.plan_json(TARGET)["scope"]["sections"]) == ["Spec > Extra", "Spec > Goal"]


def test_fenced_headings_and_duplicates_are_handled(rc: Rc) -> None:
    """DOC-2: a `#` line in a fence is text; repeated headings get ` #2`."""
    text = "# Spec\n\n```\n# not a heading\n```\n\n## Notes\none\n\n## Notes\ntwo\n"
    rc.repo.write(DOC, text)
    rc.cli(DOC, "high")
    assert rc.plan_json(TARGET)["scope"]["sections"] == [
        "Spec",
        "Spec > Notes",
        "Spec > Notes #2",
    ]


def test_outside_goal_finding_is_out_of_scope_from_round_one(rc: Rc) -> None:
    """DOC-5 (scope_note), RPT-2 wording."""
    rc.repo.write(DOC, TEXT)
    doc_round(rc, doc_cand("Spec > Scope", scope_note="outside-goal"))
    state = rc.state_json(TARGET)
    assert state["findings"][0]["origin"] == "out_of_scope"
    report = rc.cli(DOC).report
    assert re.search(r"\d+ Out of scope", report) and "Pre-existing" not in report


def test_finding_in_an_untouched_section_is_out_of_scope_in_round_three(rc: Rc) -> None:
    """DOC-5: n >= 3 and the anchor heading is not among the changed sections."""
    rc.repo.write(DOC, TEXT)
    doc_round(rc)
    second = TEXT.replace("risk text", "risk text, edited")
    rc.repo.write(DOC, second)
    doc_round(rc)
    rc.repo.write(DOC, second.replace("goal text", "goal text, edited"))
    doc_round(
        rc,
        doc_cand("Spec > Risks", snippet="risk text"),
        doc_cand("Spec > Goal"),
        tokens=("high", "--incremental"),
    )
    origins = {f["anchor"]["symbol"]: f["origin"] for f in rc.state_json(TARGET)["findings"]}
    assert origins == {"Spec > Risks": "out_of_scope", "Spec > Goal": "in_scope"}
    assert re.search(r"1 Out of scope", rc.cli(DOC).report)


def test_nonexistent_document_target_is_refused(rc: Rc) -> None:
    """DOC-1: a `.md` target that is not a file -> exit 1."""
    out = rc.cli("docs/missing.md")
    assert out.code == 1 and out.get("next") == "stop" and out.has("error")


def test_snapshot_is_refreshed_by_every_merge(rc: Rc) -> None:
    """DOC-3."""
    rc.repo.write(DOC, TEXT)
    doc_round(rc)
    second = TEXT.replace("risk text", "risk text, edited")
    rc.repo.write(DOC, second)
    doc_round(rc)
    snapshot = rc.state_dir(target=TARGET) / "doc-snapshot.md"
    assert snapshot.read_text(encoding="utf-8") == second


def test_no_repeat_list_in_document_mode_follows_the_snippet(rc: Rc) -> None:
    """RND-11 (doc), FND-17: rejected entries stay while their snippet is in the document."""
    rc.repo.write(DOC, TEXT)
    kept = doc_cand("Spec > Scope")
    refuted = doc_cand(
        "Spec > Goal", snippet="goal text", claim="the goal is vague", cls="vague goal"
    )
    out = rc.cli(DOC, "high")
    assert out.get("next") == "workflow"
    rc.merge(
        build_result(rc.plan_json(TARGET), [kept, refuted], votes={"N1.2": [False, False]}),
        TARGET,
    )
    second = TEXT.replace("risk text", "risk text, edited")
    rc.repo.write(DOC, second)
    rc.cli(DOC, "high", "--full")
    assert sorted(k["id"] for k in rc.plan_json(TARGET)["known"]) == ["-", "F1"]
    rc.merge(build_result(rc.plan_json(TARGET)), TARGET)
    rc.repo.write(DOC, second.replace("goal text", "goal reworded"))
    rc.cli(DOC, "high", "--full")
    assert [k["id"] for k in rc.plan_json(TARGET)["known"]] == ["F1"]


def test_intent_flag_in_document_mode(rc: Rc) -> None:
    """RND-16 (doc): only `--intent` is a source; none = no flag."""
    rc.repo.write(DOC, TEXT)
    without = rc.cli(DOC, "high")
    plan = rc.plan_json(TARGET)
    assert plan["intent"]["sources"] == [] and plan["intent"]["none"] is True
    assert without.get("intent") == "none"
    with_flag = rc.cli(DOC, "high", "--intent", "Keep the spec short")
    plan = rc.plan_json(TARGET)
    assert plan["intent"]["sources"] == [{"kind": "flag", "ref": "text"}]
    assert plan["intent"]["none"] is False and not with_flag.has("intent")


def test_crlf_document_round_trip(rc: Rc) -> None:
    """RPT-15: raw bytes, no newline translation: merge succeeds, round 2 is unchanged."""
    raw = TEXT.replace("\n", "\r\n").encode("utf-8")
    (rc.repo.root / "docs").mkdir()
    (rc.repo.root / DOC).write_bytes(raw)
    doc_round(rc, doc_cand("Spec > Scope"))
    assert (rc.state_dir(target=TARGET) / "doc-snapshot.md").read_bytes() == raw
    assert rc.state_json(TARGET)["sections"] == docmode.section_hashes(raw.decode("utf-8"))
    out = rc.cli(DOC)
    assert out.get("next") == "print-report"
    assert out.report.startswith("No code change since round 1")


def test_document_with_invalid_utf8_merges(rc: Rc) -> None:
    """RPT-15: bytes are decoded with `errors="replace"` at plan and at merge."""
    raw = TEXT.encode("utf-8") + b"\n## Bytes\nbad \xff byte\n"
    (rc.repo.root / "docs").mkdir()
    (rc.repo.root / DOC).write_bytes(raw)
    doc_round(rc)
    assert rc.state_json(TARGET)["change_id"] == hashlib.sha256(raw).hexdigest()
    assert rc.cli(DOC).get("next") == "print-report"
