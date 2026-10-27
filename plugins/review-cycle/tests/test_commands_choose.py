"""The RPT-18 choose step: when `plan` asks instead of planning, and what it asks."""

from __future__ import annotations

import re
from collections.abc import Callable
from pathlib import Path

import pytest
from conftest import GitRepo
from helpers_git import UTIL, Rc, append_commit, make_rc, seed_branch, set_remote_ref
from helpers_result import build_result, cand
from review_cycle import planning

DOC = "docs/spec.md"
DOC_TARGET = "doc-docs-spec-md"
DOC_TEXT = "# Spec\n\n## Goal\ngoal text\n\n## Risks\nrisk text\n"


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


def _words(lines: list[str]) -> list[str]:
    return [line.split(" | ", 1)[0] for line in lines]


def test_round_one_with_no_level_asks_only_for_the_level(rc: Rc) -> None:
    """RPT-18: `ask_level` alone; no `plan.json`, no `last-level`, nothing written."""
    seed_branch(rc.repo)
    out = rc.cli()
    assert out.get("next") == "choose"
    assert out.get("round") == "1 · code"
    assert out.get("question-level") == "Review level for round 1?"
    assert "question-scope" not in out.keys
    options = out.all("option-level")
    assert _words(options) == ["high", "medium", "low", "xhigh"]
    assert re.fullmatch(r"high \| recommended \(default\) · ~\d+ agents", options[0])
    for opt in options[1:]:
        assert re.fullmatch(r"\w+ \| ~\d+ agents", opt)
    assert out.get("recommended") == "high"
    assert not (rc.state_dir() / "plan.json").exists()
    assert not (rc.state_dir() / "state.json").exists()
    assert not (rc.data_dir / "last-level").exists()


def test_round_two_with_a_typed_level_asks_only_for_scope(rc: Rc) -> None:
    """RPT-18: `ask_scope` alone when a level is typed at round >= 2."""
    seed_branch(rc.repo)
    rc.round_trip()
    append_commit(rc.repo, UTIL, "# edit")
    before_plan = (rc.state_dir() / "plan.json").read_bytes()
    out = rc.cli("medium")
    assert out.get("next") == "choose"
    assert out.get("round") == "2 · code"
    assert "question-level" not in out.keys
    assert out.get("question-scope") == (
        "Round 2: only what changed since round 1, or the whole branch?"
    )
    options = out.all("option-scope")
    assert _words(options) == ["incremental", "full", "fresh"]
    assert options[0].startswith("incremental | recommended (only changes since round 1) · ")
    assert re.search(r"re-check of \d+ open findings? · ~\d+ agents$", options[0])
    assert options[1].startswith("full | whole branch: ")
    assert options[2].startswith("fresh | forget all findings and start again at round 1 · ")
    assert out.get("recommended") == "--incremental"
    assert (rc.state_dir() / "plan.json").read_bytes() == before_plan


def test_round_two_with_nothing_typed_asks_both(rc: Rc) -> None:
    """RPT-18: both blocks asked, in level-then-scope order, one combined `recommended:`."""
    seed_branch(rc.repo)
    rc.round_trip()
    append_commit(rc.repo, UTIL, "# edit")
    out = rc.cli()
    assert out.get("next") == "choose"
    assert out.keys.index("question-level") < out.keys.index("question-scope")
    assert out.has("question-level") and out.has("question-scope")
    assert out.get("recommended") == "high --incremental"


@pytest.mark.parametrize("flag", ["--full", "--incremental"])
def test_level_with_full_or_incremental_skips_the_choose_step(rc: Rc, flag: str) -> None:
    """RPT-18: a typed level plus an explicit scope flag resolves both; straight to a round."""
    seed_branch(rc.repo)
    rc.round_trip()
    append_commit(rc.repo, UTIL, "# edit")
    out = rc.cli("medium", flag)
    assert out.get("next") == "workflow"


def test_unchanged_with_no_level_prints_the_report_not_a_question(rc: Rc) -> None:
    """RPT-18: the unchanged check (RND-7) comes before the choose step."""
    seed_branch(rc.repo)
    rc.round_trip()
    out = rc.cli()
    assert out.get("next") == "print-report"


def test_unchanged_with_full_asks_level_then_forces_full(rc: Rc) -> None:
    """RPT-18: `--full` alone forces the rerun but still leaves the level to ask."""
    seed_branch(rc.repo)
    rc.round_trip()
    asked = rc.cli("--full")
    assert asked.get("next") == "choose"
    assert asked.has("question-level") and "question-scope" not in asked.keys
    final = rc.cli("--full", "medium")
    assert final.get("next") == "workflow"
    assert final.get("round").startswith("2 · code · medium · full")
    assert rc.plan_json()["scope"]["kind"] == "full"


def test_fresh_never_asks_for_scope(rc: Rc) -> None:
    """RPT-18: `--fresh` with state asks the level (if untyped), never the scope."""
    seed_branch(rc.repo)
    rc.round_trip()
    out = rc.cli("--fresh")
    assert out.get("next") == "choose"
    assert out.has("question-level") and "question-scope" not in out.keys
    final = rc.cli("--fresh", "medium")
    assert final.get("next") == "workflow" and final.get("round").startswith("1 · ")


def test_round_two_incremental_gives_a_since_scope_and_report_header(rc: Rc) -> None:
    """RPT-18: round 2 is no longer forced full; `--incremental` makes it `since`."""
    seed_branch(rc.repo)
    plan1, _ = rc.round_trip()
    append_commit(rc.repo, UTIL, "# edit")
    rc.cli("high", "--incremental")
    plan2 = rc.plan_json()
    assert plan2["scope"]["kind"] == "since"
    merged = rc.merge(build_result(plan2))
    assert f"since {plan1['head_sha'][:7]}" in merged.report


def test_scope_recommendation_reason_base_changed(rc: Rc) -> None:
    """RPT-18: base ref change recommends `full`, reason names old and new refs."""
    seed_branch(rc.repo)
    rc.round_trip()
    set_remote_ref(rc.repo, "origin/main")
    append_commit(rc.repo, UTIL, "# edit")
    out = rc.cli("high")
    options = out.all("option-scope")
    assert options[0].startswith("full | recommended (base changed: main → origin/main) · ")
    assert out.get("recommended") == "--full"


def test_scope_recommendation_reason_missing_file_ids(rc: Rc) -> None:
    """RPT-18: no saved `file_ids` recommends `full`."""
    seed_branch(rc.repo)
    rc.round_trip()
    state = rc.state_json()
    del state["file_ids"]
    rc.write_state(state)
    append_commit(rc.repo, UTIL, "# edit")
    out = rc.cli("high")
    options = out.all("option-scope")
    assert options[0].startswith("full | recommended (no saved file ids) · ")


def test_scope_recommendation_reason_level_raised(rc: Rc) -> None:
    """RPT-18: typing a higher level than any earlier round recommends `full`."""
    seed_branch(rc.repo)
    rc.round_trip(tokens=["low"])
    append_commit(rc.repo, UTIL, "# edit")
    out = rc.cli("xhigh")
    options = out.all("option-scope")
    assert options[0].startswith("full | recommended (level raised above earlier rounds) · ")
    assert out.get("recommended") == "--full"


def test_incremental_with_raised_level_prints_a_warning(rc: Rc) -> None:
    """RPT-18: `--incremental` overrides the `full` recommendation; a warning explains the gap."""
    seed_branch(rc.repo)
    rc.round_trip(tokens=["low"])
    append_commit(rc.repo, UTIL, "# edit")
    out = rc.cli("xhigh", "--incremental")
    assert out.get("next") == "workflow"
    assert out.get("warning") == (
        "level raised to xhigh; files outside this round were not reviewed at it (use --full)"
    )


def test_incremental_with_raised_level_in_document_mode_names_sections(rc: Rc) -> None:
    """RPT-18: the document-mode warning wording says `sections`, not `files`."""
    rc.repo.branch("feature/doc")
    rc.repo.write(DOC, DOC_TEXT)
    rc.cli(DOC, "low")
    rc.merge(build_result(rc.plan_json(DOC_TARGET)), DOC_TARGET)
    rc.repo.write(DOC, DOC_TEXT.replace("risk text", "risk text, edited"))
    out = rc.cli(DOC, "xhigh", "--incremental")
    assert out.get("warning") == (
        "level raised to xhigh; sections outside this round were not reviewed at it (use --full)"
    )


def test_base_change_under_incremental_has_no_full_scope_suffix(rc: Rc) -> None:
    """RPT-18: under `--incremental` the base-changed line omits `; full scope`."""
    seed_branch(rc.repo)
    rc.round_trip()
    set_remote_ref(rc.repo, "origin/main")
    append_commit(rc.repo, UTIL, "# edit")
    out = rc.cli("high", "--incremental")
    assert out.get("base changed") == "main → origin/main"
    assert rc.plan_json()["scope"]["kind"] == "since"


def test_doc_mode_incremental_at_round_two_is_changed_sections(rc: Rc) -> None:
    """RPT-18: the doc `n <= 2` rule is gone; round 2 can already be incremental."""
    rc.repo.branch("feature/doc")
    rc.repo.write(DOC, DOC_TEXT)
    rc.cli(DOC, "high")
    rc.merge(build_result(rc.plan_json(DOC_TARGET)), DOC_TARGET)
    rc.repo.write(DOC, DOC_TEXT.replace("risk text", "risk text, edited"))
    rc.cli(DOC, "high", "--incremental")
    assert rc.plan_json(DOC_TARGET)["scope"]["sections"] == ["Spec > Risks"]


def test_incremental_flag_without_a_level_asks_only_for_the_level(rc: Rc) -> None:
    """RPT-18: `--incremental` resolves the scope; a missing level still asks, using it to size
    the level options' agent estimate."""
    seed_branch(rc.repo)
    rc.round_trip()
    append_commit(rc.repo, UTIL, "# edit")
    out = rc.cli("--incremental")
    assert out.get("next") == "choose"
    assert out.has("question-level") and "question-scope" not in out.keys
    assert out.get("recommended") == "high"


def test_doc_mode_round_one_with_no_level_asks_only_for_the_level(rc: Rc) -> None:
    """RPT-18: the choose step's level-sizing estimate also covers document mode."""
    rc.repo.branch("feature/doc")
    rc.repo.write(DOC, DOC_TEXT)
    out = rc.cli(DOC)
    assert out.get("next") == "choose"
    assert out.get("round") == "1 · document"
    assert out.has("question-level") and "question-scope" not in out.keys
    options = out.all("option-level")
    assert options[0].startswith("high | recommended (default) · ")
    assert not (rc.state_dir(target=DOC_TARGET) / "plan.json").exists()


def test_doc_mode_round_two_with_nothing_typed_asks_both(rc: Rc) -> None:
    """RPT-18: document mode also asks both blocks, with `document` in the scope question."""
    rc.repo.branch("feature/doc")
    rc.repo.write(DOC, DOC_TEXT)
    rc.cli(DOC, "high")
    rc.merge(build_result(rc.plan_json(DOC_TARGET)), DOC_TARGET)
    rc.repo.write(DOC, DOC_TEXT.replace("risk text", "risk text, edited"))
    out = rc.cli(DOC)
    assert out.get("next") == "choose"
    assert out.has("question-level") and out.has("question-scope")
    assert out.get("question-scope") == (
        "Round 2: only what changed since round 1, or the whole document?"
    )
    scopes = out.all("option-scope")
    assert scopes[0].startswith("incremental | recommended (only changes since round 1) · ")
    assert any(s.startswith("full | whole document: ") for s in scopes)


def test_choose_step_at_round_one_writes_nothing(rc: Rc, data_dir: Path) -> None:
    """RPT-18: the choose check writes no `plan.json`/`state.json`/`last-level`."""
    seed_branch(rc.repo)
    out = rc.cli()
    assert out.get("next") == "choose"
    assert not (rc.state_dir() / "plan.json").exists()
    assert not (rc.state_dir() / "state.json").exists()
    assert not (data_dir / "last-level").exists()


def test_choose_step_at_round_two_leaves_state_untouched(rc: Rc) -> None:
    """RPT-18: at round >= 2, the choose check does not overwrite the existing files."""
    seed_branch(rc.repo)
    rc.round_trip()
    before_plan = (rc.state_dir() / "plan.json").read_bytes()
    before_state = (rc.state_dir() / "state.json").read_bytes()
    append_commit(rc.repo, UTIL, "# edit")
    out = rc.cli()
    assert out.get("next") == "choose"
    assert (rc.state_dir() / "plan.json").read_bytes() == before_plan
    assert (rc.state_dir() / "state.json").read_bytes() == before_state


def test_fresh_without_a_level_does_not_archive_before_the_level_is_answered(rc: Rc) -> None:
    """Follow-up fix: `--fresh` is read-only at the choose step; archiving (RND-8) waits until
    the choose step is satisfied, so an unanswered `--fresh` leaves everything in place."""
    seed_branch(rc.repo)
    rc.round_trip()
    sd = rc.state_dir()
    before_plan = (sd / "plan.json").read_bytes()
    before_state = (sd / "state.json").read_bytes()
    out = rc.cli("--fresh")
    assert out.get("next") == "choose"
    assert out.has("question-level") and "question-scope" not in out.keys
    assert (sd / "plan.json").read_bytes() == before_plan
    assert (sd / "state.json").read_bytes() == before_state
    assert (sd / "round-1.md").exists()
    assert not list(sd.glob("archive-*"))
    final = rc.cli("--fresh", "medium")
    assert final.get("next") == "workflow" and final.get("round").startswith("1 · ")
    assert len(list(sd.glob("archive-*"))) == 1


def _total(line: str) -> int:
    """Pull the `~<n>` agent total out of an `option-level`/`option-scope`/`agents:` line."""
    match = re.search(r"~(\d+)\b", line)
    assert match, line
    return int(match.group(1))


def test_level_option_estimate_matches_the_real_plans_agent_total_with_a_lock_file(
    rc: Rc,
) -> None:
    """Follow-up fix: the choose step's `~N agents` uses the same lock-file exclusion (RND-13)
    as the plan it describes, so picking that option gives exactly that total."""
    rc.repo.commit({"a.py": "1\n", "b.py": "2\n", "c.py": "3\n"}, "base")
    rc.repo.branch("feature/locks")
    rc.repo.commit(
        {"a.py": "1\n1\n", "b.py": "2\n2\n", "c.py": "3\n3\n", "uv.lock": "x\n" * 200}, "work"
    )
    choice = rc.cli()
    assert choice.get("next") == "choose"
    estimates = {o.split(" | ", 1)[0]: _total(o) for o in choice.all("option-level")}
    planned = rc.cli("high")
    assert planned.get("next") == "workflow"
    assert _total(planned.get("agents")) == estimates["high"]


def test_fresh_option_estimate_uses_zero_recheck_at_full_scope(rc: Rc) -> None:
    """RPT-18: `fresh` forgets every finding, so its estimate uses no re-check agents, unlike
    `full`'s at the same (typed) level and scope. Two open findings push the RND-15 batch count
    up (ceil((15 + 2) / 8) = 3 vs ceil(15 / 8) = 2), so the totals actually differ."""
    seed_branch(rc.repo, util_findings=True)
    rc.round_trip(candidates=[cand(), cand(path=UTIL, line=2, symbol="f", snippet="    x = a / b")])
    append_commit(rc.repo, UTIL, "# edit")
    out = rc.cli("high")
    options = out.all("option-scope")
    fresh_total = _total(next(o for o in options if o.startswith("fresh | ")))
    full_total = _total(next(o for o in options if o.startswith("full | ")))
    assert fresh_total < full_total


# ---------------------------------------------------------------- exact-text pins (RPT-18)


def test_level_options_exact_text_for_a_known_small_diff_fixture(rc: Rc) -> None:
    """RPT-18: exact `option-level` lines (incl. `~N agents`) for `seed_branch`'s small diff."""
    seed_branch(rc.repo)
    out = rc.cli()
    assert out.all("option-level") == [
        "high | recommended (default) · ~8 agents",
        "medium | ~6 agents",
        "low | ~6 agents",
        "xhigh | ~8 agents",
    ]
    assert out.get("recommended") == "high"


def test_level_reason_last_rounds_level(rc: Rc) -> None:
    """RPT-18: with a prior round, the recommendation reason is `last round's level`."""
    seed_branch(rc.repo)
    rc.round_trip(tokens=["medium"])
    append_commit(rc.repo, UTIL, "# edit")
    out = rc.cli()
    options = out.all("option-level")
    assert options[0].startswith("medium | recommended (last round's level) · ")
    assert out.get("recommended") == "medium --incremental"


def test_level_reason_last_used_level(rc: Rc, data_dir: Path) -> None:
    """RPT-18: no prior round but a remembered level -> reason `last used level`."""
    seed_branch(rc.repo)
    rc.cli("medium")  # writes last-level; no merge yet, so no state
    out = rc.cli()
    options = out.all("option-level")
    assert options[0].startswith("medium | recommended (last used level) · ")
    assert out.get("recommended") == "medium"


def test_level_reason_default(rc: Rc) -> None:
    """RPT-18: no prior round, no remembered level -> reason `default`, level `high`."""
    seed_branch(rc.repo)
    out = rc.cli()
    options = out.all("option-level")
    assert options[0].startswith("high | recommended (default) · ")
    assert out.get("recommended") == "high"


def test_level_reason_default_when_the_remembered_level_is_invalid(rc: Rc, data_dir: Path) -> None:
    """RPT-18: an invalid `last-level` value falls back to `high`/`default`, same as no file."""
    seed_branch(rc.repo)
    (data_dir / "last-level").write_text("bogus\n", encoding="utf-8")
    out = rc.cli()
    options = out.all("option-level")
    assert options[0].startswith("high | recommended (default) · ")
    assert out.get("recommended") == "high"


def test_level_option_order_when_the_recommendation_is_low(rc: Rc) -> None:
    """RPT-18: recommended first, then the first 3 of the priority list without it."""
    seed_branch(rc.repo)
    rc.round_trip(tokens=["low"])
    append_commit(rc.repo, UTIL, "# edit")
    out = rc.cli()
    assert _words(out.all("option-level")) == ["low", "high", "medium", "xhigh"]


def test_level_option_order_when_the_recommendation_is_max(rc: Rc) -> None:
    """RPT-18: recommended first, then the first 3 of the priority list without it."""
    seed_branch(rc.repo)
    rc.round_trip(tokens=["max"])
    append_commit(rc.repo, UTIL, "# edit")
    out = rc.cli()
    assert _words(out.all("option-level")) == ["max", "high", "medium", "low"]


def test_incremental_on_round_one_is_ignored(rc: Rc) -> None:
    """CLI-4+: round 1 ignores `--incremental`; the round stays `full`."""
    seed_branch(rc.repo)
    out = rc.cli("high", "--incremental")
    assert out.get("next") == "workflow"
    assert rc.plan_json()["scope"]["kind"] == "full"


def test_incremental_on_unchanged_code_does_not_force_a_rerun(rc: Rc) -> None:
    """RND-7: unlike `--full`, `--incremental` alone does not force a rerun of unchanged code."""
    seed_branch(rc.repo)
    rc.round_trip()
    out = rc.cli("--incremental")
    assert out.get("next") == "print-report"


def test_level_recommendation_with_a_state_of_zero_rounds() -> None:
    """RPT-18: `state["rounds"] == []` is falsy, so the recommendation still falls through to
    the remembered/default level, not `state["rounds"][-1]`."""
    state: dict[str, list[dict[str, str]]] = {"rounds": []}
    assert planning._level_recommendation(state, Path("/does/not/exist")) == ("high", "default")
