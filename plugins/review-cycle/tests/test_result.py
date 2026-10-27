"""Tests for `result` (SPECS ST-11, ST-12, ST-13, CLI-12 unwrap)."""

from __future__ import annotations

import copy
from collections.abc import Callable
from typing import Any

import pytest
from helpers_pure import candidate, full_votes, make_plan, make_result, missing_rows, verdict
from review_cycle.result import ResultError, unwrap, validate


def _basic() -> tuple[dict, dict]:
    """A plan (2 votes, no tie-break) and a valid result with one verified candidate."""
    plan = make_plan()
    cands = [candidate("N1.1")]
    return plan, make_result(plan, cands, full_votes("N1.1", [True, True]))


def _refresh(plan: dict, result: dict) -> dict:
    """Recompute the checksum after a test edited the result."""
    from review_cycle.checksum import result_checksum

    result["checksum"] = result_checksum(result)
    return result


def _err(result: dict, plan: dict) -> str:
    with pytest.raises(ResultError) as info:
        validate(result, plan)
    return str(info.value)


# --- unwrap (CLI-12, ST-13 "not an object") ---------------------------------------------------


def test_st13_unwrap_rejects_non_object() -> None:
    """ST-13: a non-object result file."""
    raws: list[object] = [[], "x", 3, None]
    for raw in raws:
        with pytest.raises(ResultError) as info:
            unwrap(raw)
        assert str(info.value) == "error: result is not a JSON object"


def test_cli12_unwrap_runtime_output_file() -> None:
    """CLI-12: `result` key and no `provenance` key -> the inner object."""
    inner = {"provenance": "review-cycle/workflows/review.js", "v": 1}
    assert unwrap({"result": inner, "calls": []}) == inner


def test_cli12_unwrap_session_copy_is_returned_as_is() -> None:
    """CLI-12: a `provenance` key means the file is already the result."""
    raw = {"provenance": "review-cycle/workflows/review.js", "result": {"x": 1}}
    assert unwrap(raw) == raw
    plain = {"v": 1, "started": False}
    assert unwrap(plain) == plain


# --- happy path --------------------------------------------------------------------------------


def test_st12_valid_result_passes() -> None:
    """ST-12: a complete, consistent result validates without error."""
    plan, result = _basic()
    validate(result, plan)


def test_st12_valid_result_with_missing_rows_passes() -> None:
    """ST-12: coverage may be met through `missing`."""
    plan = make_plan()
    result = make_result(
        plan,
        [candidate("N1.1")],
        full_votes("N1.1", [True, None]),
        missing=missing_rows("N1.1", [True, None]),
    )
    validate(result, plan)


def test_st12_valid_result_with_dropped_and_recheck_passes() -> None:
    """ST-12: dropped candidates need no verdicts; recheck ids need coverage."""
    plan = make_plan(recheck_ids=["F1"])
    verdicts = full_votes("N1.1", [True, False]) + full_votes("F1", [True, True], kind="recheck")
    result = make_result(
        plan,
        [candidate("N1.1"), candidate("N1.2")],
        verdicts + full_votes("N1.2", [False, False]),
        dropped=[{"id": "N2.1", "dup_of": "N1.1"}],
    )
    validate(result, plan)


# --- ST-13 messages, in order ------------------------------------------------------------------


def test_st13_provenance() -> None:
    plan, result = _basic()
    result["provenance"] = "someone/else.js"
    assert _err(result, plan) == "error: result provenance is not review-cycle/workflows/review.js"


def test_st13_version() -> None:
    plan, result = _basic()
    result["v"] = 2
    assert _err(result, plan) == "error: result version 2 not supported"


def test_st13_not_started() -> None:
    plan = make_plan()
    result = {
        "provenance": "review-cycle/workflows/review.js",
        "v": 1,
        "started": False,
        "reason": "haiku-verifier",
        "next": "x",
    }
    assert _err(result, plan) == "error: workflow did not start: haiku-verifier"


def test_st13_plan_id() -> None:
    plan, result = _basic()
    result["plan_id"] = "other-plan"
    assert _err(result, plan) == "error: result is for plan other-plan, current plan is plan-1"


def test_st13_plan_status() -> None:
    plan, result = _basic()
    plan["status"] = "merged"
    assert _err(result, plan) == "error: plan is not ready (status merged)"


def test_st12_plan_id_is_checked_before_plan_status() -> None:
    """ST-12: order follows the ST-13 rows (plan id, then plan status)."""
    plan, result = _basic()
    plan["status"] = "merged"
    result["plan_id"] = "other"
    assert _err(result, plan).startswith("error: result is for plan other")


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("level", "high"),
        ("mode", "document"),
        ("finders", []),
        ("votes", ["opus"]),
        ("tiebreak", "opus"),
        ("recheck_ids", ["F9"]),
    ],
)
def test_st13_echo_differs(field: str, value: Any) -> None:
    plan, result = _basic()
    result["echo"][field] = value
    assert _err(result, plan) == f"error: result echo differs from plan args: {field}"


def test_st13_missing_top_level_field() -> None:
    plan, result = _basic()
    del result["candidates"]
    assert _err(result, plan) == "error: field candidates is missing"


def test_st13_missing_nested_candidate_field() -> None:
    plan, result = _basic()
    del result["candidates"][0]["claim"]
    assert _err(result, plan) == "error: field candidates[0].claim is missing"


def test_st13_missing_verdict_field() -> None:
    plan, result = _basic()
    del result["verdicts"][1]["holds"]
    assert _err(result, plan) == "error: field verdicts[1].holds is missing"


def _set(path: list[str | int], value: Any) -> Callable[[dict], None]:
    def apply(result: dict) -> None:
        node: Any = result
        for key in path[:-1]:
            node = node[key]
        node[path[-1]] = value

    return apply


TYPE_CASES: list[tuple[str, Callable[[dict], None]]] = [
    ("candidates[0].id", _set(["candidates", 0, "id"], 5)),
    ("candidates[0].category", _set(["candidates", 0, "category"], "ambiguity")),
    ("candidates[0].class", _set(["candidates", 0, "class"], 1)),
    ("candidates[0].path", _set(["candidates", 0, "path"], "")),
    ("candidates[0].line", _set(["candidates", 0, "line"], -1)),
    ("candidates[0].line", _set(["candidates", 0, "line"], "3")),
    ("candidates[0].symbol", _set(["candidates", 0, "symbol"], None)),
    ("candidates[0].claim", _set(["candidates", 0, "claim"], "")),
    ("candidates[0].trigger", _set(["candidates", 0, "trigger"], 1)),
    ("candidates[0].evidence", _set(["candidates", 0, "evidence"], 1)),
    ("candidates[0].expected", _set(["candidates", 0, "expected"], 1)),
    ("candidates[0].broken_by.path", _set(["candidates", 0, "broken_by", "path"], 1)),
    ("candidates[0].broken_by.line", _set(["candidates", 0, "broken_by", "line"], -2)),
    ("candidates[0].scope_note", _set(["candidates", 0, "scope_note"], "other")),
    ("candidates[0].lens", _set(["candidates", 0, "lens"], 1)),
    ("candidates[0].finder", _set(["candidates", 0, "finder"], -1)),
    ("candidates[0].of_class", _set(["candidates", 0, "of_class"], 1)),
    ("verdicts[0].item_id", _set(["verdicts", 0, "item_id"], 1)),
    ("verdicts[0].kind", _set(["verdicts", 0, "kind"], "old")),
    ("verdicts[0].role", _set(["verdicts", 0, "role"], "judge")),
    ("verdicts[0].slot", _set(["verdicts", 0, "slot"], -1)),
    ("verdicts[0].model", _set(["verdicts", 0, "model"], 1)),
    ("verdicts[0].batch", _set(["verdicts", 0, "batch"], -1)),
    ("verdicts[0].holds", _set(["verdicts", 0, "holds"], 1)),
    ("verdicts[0].severity", _set(["verdicts", 0, "severity"], "high")),
    ("verdicts[0].reason", _set(["verdicts", 0, "reason"], 1)),
    ("verdicts[0].evidence", _set(["verdicts", 0, "evidence"], 1)),
    ("verdicts[0].trigger", _set(["verdicts", 0, "trigger"], 1)),
    ("verdicts[0].prevented_by", _set(["verdicts", 0, "prevented_by"], 1)),
    (
        "verdicts[0].needs_decision.criterion",
        _set(["verdicts", 0, "needs_decision", "criterion"], 4),
    ),
    (
        "verdicts[0].needs_decision.before",
        _set(["verdicts", 0, "needs_decision", "before"], 1),
    ),
    (
        "verdicts[0].needs_decision.options",
        _set(["verdicts", 0, "needs_decision", "options"], "x"),
    ),
    (
        "verdicts[0].needs_decision.options[0].label",
        _set(["verdicts", 0, "needs_decision", "options"], [{"label": 1, "observable": "o"}]),
    ),
    ("dropped[0].id", _set(["dropped", 0, "id"], 1)),
    ("dropped[0].dup_of", _set(["dropped", 0, "dup_of"], 1)),
    ("missing[0].role", _set(["missing", 0, "role"], "judge")),
    ("missing[0].slot", _set(["missing", 0, "slot"], "0")),
    ("stats.agents_started", _set(["stats", "agents_started"], -1)),
    ("stats.agents_returned", _set(["stats", "agents_returned"], "6")),
    ("stats.finders_null", _set(["stats", "finders_null"], None)),
    ("stats.verifiers_null", _set(["stats", "verifiers_null"], 1.5)),
    ("log", _set(["log"], "text")),
    ("checksum", _set(["checksum"], "ABCDEF12")),
    ("checksum", _set(["checksum"], "abc")),
]


def _typed_base() -> tuple[dict, dict]:
    """A result with every ST-11 array non-empty so each type row has a target."""
    plan = make_plan()
    cands = [candidate("N1.1")]
    holds: list[bool | None] = [True, None]
    result = make_result(
        plan,
        cands,
        full_votes("N1.1", holds),
        missing=missing_rows("N1.1", holds),
        dropped=[{"id": "N2.1", "dup_of": "N1.1"}],
        log=["a line"],
    )
    return plan, result


@pytest.mark.parametrize(
    ("path", "mutate"), TYPE_CASES, ids=[f"{p}-{i}" for i, (p, _) in enumerate(TYPE_CASES)]
)
def test_st13_wrong_type_or_value(path: str, mutate: Callable[[dict], None]) -> None:
    """ST-13: `field <path> must be <type>` for each type row; type text is not pinned."""
    plan, result = _typed_base()
    mutate(result)
    message = _err(result, plan)
    assert message.startswith(f"error: field {path} must be ")


def test_st13_candidate_category_enum_follows_mode() -> None:
    """ST-9/ST-13: document categories are valid in document mode, code ones are not."""
    plan = make_plan(mode="document")
    good = make_result(
        plan, [candidate("N1.1", category="ambiguity")], full_votes("N1.1", [True, True])
    )
    validate(good, plan)
    bad = make_result(plan, [candidate("N1.1", category="logic")], full_votes("N1.1", [True, True]))
    assert _err(bad, plan).startswith("error: field candidates[0].category must be ")


def test_st13_duplicate_candidate_id() -> None:
    plan = make_plan()
    result = make_result(
        plan,
        [candidate("N1.1"), candidate("N1.1")],
        full_votes("N1.1", [True, True]),
    )
    assert _err(result, plan) == "error: duplicate candidate id N1.1"


def test_st13_unknown_item() -> None:
    plan, result = _basic()
    result["verdicts"].append(verdict("N9.9", True, slot=0))
    assert _err(_refresh(plan, result), plan) == "error: verdict for unknown item N9.9"


def test_st13_verdict_for_dropped_candidate_is_unknown() -> None:
    """ST-12: item ids must be candidate ids (not dropped) or recheck ids."""
    plan = make_plan()
    result = make_result(
        plan,
        [candidate("N1.1")],
        full_votes("N1.1", [True, True]) + full_votes("N2.1", [True, True]),
        dropped=[{"id": "N2.1", "dup_of": "N1.1"}],
    )
    assert _err(result, plan) == "error: verdict for unknown item N2.1"


def test_st13_slot_out_of_range() -> None:
    plan, result = _basic()
    result["verdicts"].append(verdict("N1.1", True, slot=2))
    assert _err(_refresh(plan, result), plan) == "error: vote slot 2 out of range for N1.1"


def test_st13_tiebreak_without_level_tiebreak() -> None:
    plan, result = _basic()
    result["verdicts"].append(verdict("N1.1", True, role="tiebreak", slot=0))
    assert (
        _err(_refresh(plan, result), plan) == "error: tie-break verdict but level has no tie-break"
    )


@pytest.mark.parametrize(
    ("drop_index", "expected"),
    [(0, "N1.1/vote/0"), (1, "N1.1/vote/1")],
)
def test_st13_coverage_vote_slot_missing(drop_index: int, expected: str) -> None:
    """ST-13: partial verdicts without `missing` -> coverage error naming item/role/slot."""
    plan, result = _basic()
    del result["verdicts"][drop_index]
    assert _err(_refresh(plan, result), plan) == f"error: verdict coverage incomplete: {expected}"


def test_st13_coverage_recheck_item() -> None:
    plan = make_plan(recheck_ids=["F1"])
    result = make_result(plan, [], full_votes("F1", [True], kind="recheck"))
    assert _err(result, plan) == "error: verdict coverage incomplete: F1/vote/1"


def _tiebreak_plan() -> dict:
    return make_plan(
        level="high", tiebreak="opus", keep_rule="all2_tiebreak", votes=("sonnet", "opus")
    )


def test_st13_coverage_tiebreak_required_on_split() -> None:
    """ST-12: a split vote needs a tie-break verdict or a `missing` row."""
    plan = _tiebreak_plan()
    result = make_result(plan, [candidate("N1.1")], full_votes("N1.1", [True, False]))
    assert _err(result, plan) == "error: verdict coverage incomplete: N1.1/tiebreak/0"


def test_st13_coverage_tiebreak_required_when_a_vote_is_missing() -> None:
    """ST-12: a missing vote counts as not holding, so one holder plus one missing -> tie-break."""
    plan = _tiebreak_plan()
    holds: list[bool | None] = [True, None]
    result = make_result(
        plan,
        [candidate("N1.1")],
        full_votes("N1.1", holds),
        missing=missing_rows("N1.1", holds),
    )
    assert _err(result, plan) == "error: verdict coverage incomplete: N1.1/tiebreak/0"


@pytest.mark.parametrize("holds", [[True, True], [False, False]])
def test_st12_no_tiebreak_needed_when_votes_agree(holds: list[bool | None]) -> None:
    plan = _tiebreak_plan()
    result = make_result(plan, [candidate("N1.1")], full_votes("N1.1", holds))
    validate(result, plan)


def test_st12_tiebreak_covered_by_verdict_or_missing() -> None:
    plan = _tiebreak_plan()
    votes = full_votes("N1.1", [True, False])
    with_verdict = make_result(
        plan,
        [candidate("N1.1")],
        votes + [verdict("N1.1", True, role="tiebreak", slot=0, model="opus")],
    )
    validate(with_verdict, plan)
    with_missing = make_result(
        plan,
        [candidate("N1.1")],
        votes,
        missing=[{"item_id": "N1.1", "role": "tiebreak", "slot": 0}],
    )
    validate(with_missing, plan)


def test_st13_checksum_mismatch() -> None:
    plan, result = _basic()
    result["candidates"][0]["claim"] += "x"
    assert _err(result, plan) == "error: result checksum mismatch"


def test_st13_checksum_off_by_one_char() -> None:
    plan, result = _basic()
    good = result["checksum"]
    result["checksum"] = good[:-1] + ("0" if good[-1] != "0" else "1")
    assert _err(result, plan) == "error: result checksum mismatch"


def test_st12_checks_run_in_st13_order() -> None:
    """ST-12: version beats plan id; echo beats field types; types beat duplicate ids."""
    plan, result = _basic()
    broken = copy.deepcopy(result)
    broken["v"] = 3
    broken["plan_id"] = "other"
    assert _err(broken, plan) == "error: result version 3 not supported"

    broken = copy.deepcopy(result)
    broken["echo"]["level"] = "max"
    broken["candidates"][0]["line"] = -1
    assert _err(broken, plan).startswith("error: result echo differs")

    broken = copy.deepcopy(result)
    broken["candidates"].append(copy.deepcopy(broken["candidates"][0]))
    broken["candidates"][0]["line"] = -1
    assert _err(broken, plan).startswith("error: field candidates[0].line must be ")


def test_st12_validate_writes_nothing_and_does_not_mutate() -> None:
    """ST-12/§12: validation is read-only."""
    plan, result = _basic()
    before_r, before_p = copy.deepcopy(result), copy.deepcopy(plan)
    validate(result, plan)
    assert result == before_r
    assert plan == before_p


def test_st12_tiebreak_plan_all_refuting_or_missing_needs_no_tiebreak_row() -> None:
    """ST-12: votes [False, missing] have no holder, so no tie-break is expected."""
    plan = _tiebreak_plan()
    holds: list[bool | None] = [False, None]
    result = make_result(
        plan,
        [candidate("N1.1")],
        full_votes("N1.1", holds),
        missing=missing_rows("N1.1", holds),
    )
    validate(result, plan)


def test_st13_recheck_item_with_split_votes_needs_its_tiebreak_row() -> None:
    """ST-12: tie-break coverage applies to recheck items as well."""
    plan = make_plan(
        level="high",
        tiebreak="opus",
        keep_rule="all2_tiebreak",
        votes=("sonnet", "opus"),
        recheck_ids=["F1"],
    )
    result = make_result(plan, [], full_votes("F1", [True, False], kind="recheck"))
    assert _err(result, plan) == "error: verdict coverage incomplete: F1/tiebreak/0"


# --- code review R2 -----------------------------------------------------------------------------


@pytest.mark.parametrize("version", [True, 1.0])
def test_st13_version_must_be_the_integer_one(version: object) -> None:
    plan, result = _basic()
    result["v"] = version
    assert _err(result, plan) == f"error: result version {version} not supported"


def test_st12_verdict_kind_must_match_the_item() -> None:
    plan = make_plan(recheck_ids=["F1"])
    verdicts = full_votes("N1.1", [True, True], kind="recheck") + full_votes(
        "F1", [True, True], kind="recheck"
    )
    result = make_result(plan, [candidate("N1.1")], verdicts)
    assert _err(result, plan).startswith("error: field verdicts[0].kind must be ")
    verdicts = full_votes("N1.1", [True, True]) + full_votes("F1", [True, True])
    result = make_result(plan, [candidate("N1.1")], verdicts)
    assert _err(result, plan).startswith("error: field verdicts[2].kind must be ")


def test_st12_tiebreak_rows_must_use_slot_zero() -> None:
    plan = _tiebreak_plan()
    votes = full_votes("N1.1", [True, False])
    bad = verdict("N1.1", True, role="tiebreak", slot=1, model="opus")
    result = make_result(plan, [candidate("N1.1")], votes + [bad])
    assert _err(result, plan).startswith("error: field verdicts[2].slot must be ")
