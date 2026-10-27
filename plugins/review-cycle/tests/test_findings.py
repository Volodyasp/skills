"""Tests for the pure parts of `findings` (SPECS FND-4..FND-9, FND-13..FND-18)."""

from __future__ import annotations

import copy
import hashlib
from typing import Any

import pytest
from helpers_pure import (
    candidate,
    full_votes,
    make_finding,
    make_plan,
    make_result,
    make_round,
    make_state,
    missing_rows,
    nd,
    sha,
    verdict,
)
from review_cycle.findings import (
    MergeContext,
    MergeOutcome,
    apply_mark,
    fingerprint,
    keep_outcome,
    locate_anchor,
    match,
    merge_round,
    nit_cap,
    norm_snippet,
    origin_code,
    recheck_outcome,
    rule_suggestions,
    section_of,
    severity_of,
    snippet_present,
    validate_decision,
)

NOW = "2026-10-26T12:00:00Z"


def fnd(fid: str = "F1", **kw: Any) -> dict:
    """Finding whose fingerprint is the real one for its anchor."""
    cat = kw.get("category", "logic")
    fp = fingerprint(
        cat, kw.get("path", "src/a.py"), kw.get("symbol", "f"), kw.get("snippet", "x = 1")
    )
    kw.setdefault("fingerprint", fp)
    return make_finding(fid, **kw)


# --- FND-4 norm_snippet / fingerprint -----------------------------------------------------------


def test_fnd4_norm_snippet_strips_collapses_and_drops_empty_lines() -> None:
    raw = "  if  x:\t\n\n      return   1  \n   \n"
    assert norm_snippet(raw) == "if x:\nreturn 1"


def test_fnd4_norm_snippet_empty_and_single() -> None:
    assert norm_snippet("") == ""
    assert norm_snippet("  \n\t\n") == ""
    assert norm_snippet("  a   b ") == "a b"


def test_fnd4_norm_snippet_cyrillic_and_crlf() -> None:
    assert norm_snippet("  если   баланс\r\n\r\n   вернуть  1 ") == "если баланс\nвернуть 1"


def test_fnd4_fingerprint_is_first_16_hex_of_sha256() -> None:
    expected = hashlib.sha256("logic\x1fsrc/a.py\x1ff\x1fa b\nc".encode()).hexdigest()[:16]
    assert fingerprint("logic", "src/a.py", "f", "  a   b \n\n c ") == expected
    assert len(expected) == 16


def test_fnd4_fingerprint_cyrillic() -> None:
    snippet = "если   баланс"
    expected = hashlib.sha256(
        "логика\x1fпуть/файл.py\x1fфункция\x1fесли баланс".encode()
    ).hexdigest()
    assert fingerprint("логика", "путь/файл.py", "функция", snippet) == expected[:16]


def test_fnd4_fingerprint_ignores_whitespace_but_not_other_fields() -> None:
    base = fingerprint("logic", "a.py", "f", "x = 1")
    assert fingerprint("logic", "a.py", "f", "  x   =  1 \n") == base
    assert fingerprint("rule", "a.py", "f", "x = 1") != base
    assert fingerprint("logic", "b.py", "f", "x = 1") != base
    assert fingerprint("logic", "a.py", "g", "x = 1") != base
    assert fingerprint("logic", "a.py", "f", "x = 2") != base


# --- FND-5 match --------------------------------------------------------------------------------


def _cand(**kw: Any) -> dict:
    return candidate("N1.1", **kw)


def test_fnd5_exact_fingerprint_hit_when_snippet_moved_to_another_line() -> None:
    """FND-5: the line is not part of the fingerprint, so a moved snippet is still the same."""
    f = fnd("F1", line=5)
    hit = match(_cand(line=400), [f])
    assert hit is not None
    assert hit["id"] == "F1"


def test_fnd5_exact_fingerprint_beats_a_fuzzy_candidate_with_lower_id() -> None:
    fuzzy = fnd("F1", snippet="x = compute(a, b, c)")
    exact = fnd("F2", snippet="x = compute(a, b)")
    hit = match(_cand(snippet="x = compute(a, b)", claim=exact["claim"]), [fuzzy, exact])
    assert hit is not None
    assert hit["id"] == "F2"


def test_fnd5_fuzzy_hit_same_path_symbol_similar_snippet_and_claim() -> None:
    f = fnd("F1", snippet="x = compute(a, b)")
    hit = match(_cand(snippet="x = compute(a, b, c)", **{"class": "other class"}), [f])
    assert hit is not None
    assert hit["id"] == "F1"


def test_fnd5_fuzzy_cyrillic() -> None:
    f = fnd(
        "F1",
        snippet="if баланс < сумма:\n    raise Ошибка()",
        **{"class": "граница сравнения"},
        claim="сравнение неверное",
    )
    cand = _cand(
        snippet="if баланс <= сумма:\n    raise Ошибка()",
        claim="совсем другой текст",
        **{"class": "граница сравнения"},
    )
    hit = match(cand, [f])
    assert hit is not None
    assert hit["id"] == "F1"


def test_fnd5_snippet_below_080_is_no_hit() -> None:
    f = fnd("F1", snippet="retry charges twice")
    assert match(_cand(snippet="retry charges twice on timeout"), [f]) is None


def test_fnd5_class_or_claim_must_reach_050() -> None:
    f = fnd("F1", snippet="x = compute(a, b)", claim="lock not released", **{"class": "locks"})
    cand = _cand(
        snippet="x = compute(a, b, c)",
        claim="totally different words here",
        **{"class": "zzzzzz"},
    )
    assert match(cand, [f]) is None
    by_claim = _cand(
        snippet="x = compute(a, b, c)", claim="lock not released", **{"class": "zzzzzz"}
    )
    assert match(by_claim, [f]) is not None
    by_class = _cand(snippet="x = compute(a, b, c)", claim="unrelated words", **{"class": "locks"})
    assert match(by_class, [f]) is not None


@pytest.mark.parametrize(("path", "symbol"), [("src/b.py", "f"), ("src/a.py", "g")])
def test_fnd5_fuzzy_needs_same_path_and_symbol(path: str, symbol: str) -> None:
    f = fnd("F1", snippet="x = compute(a, b)")
    cand = _cand(path=path, symbol=symbol, snippet="x = compute(a, b, c)", claim=f["claim"])
    assert match(cand, [f]) is None


def test_fnd5_highest_snippet_ratio_wins() -> None:
    near = fnd("F1", snippet="x = compute(a, b, c, d)")
    nearer = fnd("F2", snippet="x = compute(a, b, c)")
    hit = match(_cand(snippet="x = compute(a, b, c)!", claim=near["claim"]), [near, nearer])
    assert hit is not None
    assert hit["id"] == "F2"


def test_fnd5_ties_go_to_the_lowest_id_numerically() -> None:
    f10 = fnd("F10", snippet="x = compute(a, b)", fingerprint="stale-10")
    f2 = fnd("F2", snippet="x = compute(a, b)", fingerprint="stale-2")
    hit = match(_cand(snippet="x = compute(a, b, c)", claim=f2["claim"]), [f10, f2])
    assert hit is not None
    assert hit["id"] == "F2"


def test_fnd5_no_findings_no_hit() -> None:
    assert match(_cand(), []) is None


# --- FND-6 keep_outcome -------------------------------------------------------------------------


def v(holds: bool | None) -> dict | None:
    return None if holds is None else {"holds": holds, "severity": "important" if holds else ""}


T, F, N = True, False, None

KEEP_TABLE = [
    # all2
    ("all2", [T, T], None, "confirmed"),
    ("all2", [T, N], None, "uncertain"),
    ("all2", [N, T], None, "uncertain"),
    ("all2", [T, F], None, "rejected"),
    ("all2", [F, T], None, "rejected"),
    ("all2", [F, F], None, "rejected"),
    ("all2", [F, N], None, "rejected"),
    ("all2", [N, F], None, "rejected"),
    ("all2", [N, N], None, "uncertain"),
    # all2_tiebreak
    ("all2_tiebreak", [T, T], None, "confirmed"),
    ("all2_tiebreak", [F, F], None, "rejected"),
    ("all2_tiebreak", [F, N], None, "rejected"),
    ("all2_tiebreak", [T, F], T, "confirmed"),
    ("all2_tiebreak", [F, T], T, "confirmed"),
    ("all2_tiebreak", [T, F], F, "rejected"),
    ("all2_tiebreak", [T, F], N, "uncertain"),
    ("all2_tiebreak", [T, N], T, "confirmed"),
    ("all2_tiebreak", [N, T], F, "rejected"),
    ("all2_tiebreak", [T, N], N, "uncertain"),
    ("all2_tiebreak", [N, N], N, "uncertain"),
    # maj3
    ("maj3", [T, T, T], None, "confirmed"),
    ("maj3", [T, T, F], None, "confirmed"),
    ("maj3", [T, T, N], None, "confirmed"),
    ("maj3", [N, T, T], None, "confirmed"),
    ("maj3", [T, F, F], None, "uncertain"),
    ("maj3", [T, F, N], None, "uncertain"),
    ("maj3", [T, N, N], None, "uncertain"),
    ("maj3", [F, F, F], None, "rejected"),
    ("maj3", [F, F, N], None, "rejected"),
    ("maj3", [F, N, N], None, "rejected"),
    ("maj3", [N, N, N], None, "uncertain"),
]


@pytest.mark.parametrize(("rule", "votes", "tiebreak", "expected"), KEEP_TABLE)
def test_fnd6_keep_outcome_truth_table(
    rule: str, votes: list[bool | None], tiebreak: bool | None, expected: str
) -> None:
    assert keep_outcome(rule, [v(h) for h in votes], v(tiebreak)) == expected


def test_fnd6_no_vote_at_all_is_uncertain_never_rejected_for_every_rule() -> None:
    assert keep_outcome("all2", [None, None], None) == "uncertain"
    assert keep_outcome("all2_tiebreak", [None, None], None) == "uncertain"
    assert keep_outcome("maj3", [None, None, None], None) == "uncertain"


# --- FND-7 severity_of --------------------------------------------------------------------------


def _sev(*levels: str) -> list[dict]:
    return [{"holds": True, "severity": s} for s in levels]


@pytest.mark.parametrize(
    ("levels", "expected"),
    [
        (["important"], ("important", False)),
        (["nit"], ("nit", False)),
        (["important", "important"], ("important", False)),
        (["nit", "nit"], ("nit", False)),
        (["important", "nit"], ("important", True)),
        (["nit", "important"], ("important", True)),
        (["nit", "nit", "important"], ("important", True)),
    ],
)
def test_fnd7_severity_of(levels: list[str], expected: tuple[str, bool]) -> None:
    assert severity_of(_sev(*levels)) == expected


def test_fnd7_no_confirming_verdict_is_nit() -> None:
    assert severity_of([]) == ("nit", False)


# --- FND-8 validate_decision --------------------------------------------------------------------

INTENT = ["# Goal\nThe system must\n  never   double charge a customer.\n"]


def test_fnd8_c1_valid_when_before_after_differ() -> None:
    flag = nd(1, before="refund 100", after="refund 30")
    assert validate_decision([flag], []) == flag


@pytest.mark.parametrize(("before", "after"), [("", "x"), ("x", ""), ("", ""), ("same", "same")])
def test_fnd8_c1_rejected(before: str, after: str) -> None:
    assert validate_decision([nd(1, before=before, after=after)], []) is None


def test_fnd8_c2_valid_when_quote_is_in_intent_modulo_whitespace() -> None:
    flag = nd(2, intent_quote="must never double charge")
    assert validate_decision([flag], INTENT) == flag


def test_fnd8_c2_valid_via_any_intent_text() -> None:
    flag = nd(2, intent_quote="linked doc says X")
    assert validate_decision([flag], ["nothing", "the linked doc  says\nX."]) == flag


@pytest.mark.parametrize("quote", ["", "   ", "must double charge", "MUST never double charge"])
def test_fnd8_c2_rejected(quote: str) -> None:
    assert validate_decision([nd(2, intent_quote=quote)], INTENT) is None


def test_fnd8_c2_without_intent_texts_is_rejected() -> None:
    assert validate_decision([nd(2, intent_quote="anything")], []) is None


def test_fnd8_c3_valid_with_two_complete_options() -> None:
    flag = nd(3, options=[{"label": "A", "observable": "x"}, {"label": "B", "observable": "y"}])
    assert validate_decision([flag], []) == flag


@pytest.mark.parametrize(
    "options",
    [
        [],
        [{"label": "A", "observable": "x"}],
        [{"label": "A", "observable": "x"}, {"label": "", "observable": "y"}],
        [{"label": "A", "observable": "x"}, {"label": "B", "observable": ""}],
    ],
)
def test_fnd8_c3_rejected(options: list[dict]) -> None:
    assert validate_decision([nd(3, options=options)], []) is None


def test_fnd8_lowest_valid_criterion_is_kept() -> None:
    c3 = nd(3, options=[{"label": "A", "observable": "x"}, {"label": "B", "observable": "y"}])
    c1 = nd(1, before="a", after="b")
    assert validate_decision([c3, c1], []) == c1


def test_fnd8_invalid_flags_are_dropped_in_favour_of_a_valid_one() -> None:
    bad1 = nd(1, before="same", after="same")
    c3 = nd(3, options=[{"label": "A", "observable": "x"}, {"label": "B", "observable": "y"}])
    assert validate_decision([bad1, c3], []) == c3


def test_fnd8_criterion_zero_and_empty_list_give_none() -> None:
    assert validate_decision([nd(0)], []) is None
    assert validate_decision([], []) is None


# --- FND-9 locate_anchor / origin_code ----------------------------------------------------------

FILE = "def f(items):\n    # init\n    x = 1\n\n    y = 2\n    return x\n"


def test_fnd9_locate_anchor_single_line() -> None:
    assert locate_anchor(FILE, "x = 1", 99) == 3


def test_fnd9_locate_anchor_multi_line_skips_blank_lines_and_ignores_indent() -> None:
    assert locate_anchor(FILE, "x = 1\n  y = 2", 99) == 3


def test_fnd9_locate_anchor_first_match_wins() -> None:
    assert locate_anchor("a\nx\nb\nx\n", "x", 99) == 2


@pytest.mark.parametrize(
    ("text", "snippet"),
    [(None, "x = 1"), (FILE, "not there"), (FILE, ""), (FILE, "y = 2\nx = 1")],
)
def test_fnd9_locate_anchor_falls_back_to_reported_line(text: str | None, snippet: str) -> None:
    assert locate_anchor(text, snippet, 42) == 42


def test_fnd9_locate_anchor_cyrillic() -> None:
    assert locate_anchor("# заголовок\nесли  баланс < 0:\n", "если баланс < 0:", 1) == 2


RANGES = {"src/a.py": [(10, 12), (30, 30)], "src/b.py": [(5, 8)]}


@pytest.mark.parametrize("line", [10, 11, 12, 30])
def test_fnd9_line_in_changed_range_is_introduced(line: int) -> None:
    assert origin_code("src/a.py", line, {"path": "", "line": 0}, RANGES) == "introduced"


@pytest.mark.parametrize("line", [9, 13, 29, 31])
def test_fnd9_line_outside_ranges_without_cause_is_pre_existing(line: int) -> None:
    assert origin_code("src/a.py", line, {"path": "", "line": 0}, RANGES) == "pre_existing"


def test_fnd9_broken_by_in_changed_range() -> None:
    assert (
        origin_code("src/a.py", 50, {"path": "src/b.py", "line": 6}, RANGES) == "broken_by_change"
    )


@pytest.mark.parametrize(
    "broken_by",
    [
        {"path": "src/b.py", "line": 9},
        {"path": "src/c.py", "line": 6},
        {"path": "", "line": 6},
        {"path": "src/b.py", "line": 0},
    ],
)
def test_fnd9_broken_by_outside_ranges_is_pre_existing(broken_by: dict) -> None:
    assert origin_code("src/a.py", 50, broken_by, RANGES) == "pre_existing"


def test_fnd9_path_without_ranges_is_pre_existing() -> None:
    assert origin_code("src/new.py", 1, {"path": "", "line": 0}, RANGES) == "pre_existing"


# --- FND-13 nit_cap -----------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Report at most 3 nits per round.", 3),
        ("At most three nits.", 3),
        ("AT MOST TEN NITS please", 10),
        ("at most one nit", 1),
        ("at most 12 nits", 12),
        ("at most 0 nits", 0),
        ("at most five nits, but at most two nits", 5),
        ("Intro\nat most four nits\n", 4),
    ],
)
def test_fnd13_nit_cap_regex(text: str, expected: int) -> None:
    assert nit_cap(text) == expected


@pytest.mark.parametrize(
    "text",
    [None, "", "no cap stated", "at most eleven nits", "at most some nits", "at most 3 issues"],
)
def test_fnd13_nit_cap_default_is_five(text: str | None) -> None:
    assert nit_cap(text) == 5


# --- FND-14 section_of --------------------------------------------------------------------------

SECTION_CASES: list[tuple[dict, str | None]] = [
    ({"severity": "important"}, "agent_can_fix"),
    ({"severity": "nit"}, "nit"),
    ({"verdict": "uncertain"}, "uncertain"),
    ({"verdict": "uncertain", "severity": "nit"}, "uncertain"),
    ({"needs_decision": {"criterion": 1}}, "needs_decision"),
    ({"needs_decision": {"criterion": 1}, "verdict": "uncertain"}, "needs_decision"),
    ({"origin": "pre_existing"}, "pre_existing"),
    ({"origin": "out_of_scope"}, "out_of_scope"),
    ({"origin": "in_scope"}, "agent_can_fix"),
    ({"origin": "broken_by_change", "severity": "nit"}, "nit"),
    ({"origin": "pre_existing", "needs_decision": {"criterion": 2}}, "pre_existing"),
    ({"origin": "pre_existing", "verdict": "uncertain"}, "pre_existing"),
    ({"hidden_reason": "outside_scope"}, None),
    ({"hidden_reason": "outside_scope", "origin": "pre_existing"}, None),
    ({"status": "fixed"}, None),
    ({"status": "wontfix"}, None),
    ({"status": "intentional", "reopen_round": 1}, None),
    ({"status": "wontfix", "reopen_round": 2}, "reopen"),
    ({"status": "wrong", "reopen_round": 2}, "reopen"),
    ({"status": "superseded", "reopen_round": 3}, None),
]


@pytest.mark.parametrize(("overrides", "expected"), SECTION_CASES)
def test_fnd14_section_of(overrides: dict, expected: str | None) -> None:
    assert section_of(make_finding("F1", **overrides), 2) == expected


# --- FND-15 apply_mark --------------------------------------------------------------------------


def _marked_state(**finding_kw: Any) -> dict:
    return make_state([fnd("F1", **finding_kw)], rounds=[make_round(1), make_round(2)])


def _finding(state: dict) -> dict:
    return state["findings"][0]


DECIDE = ["intentional", "wontfix", "wrong", "superseded"]
LINE_KEYS = {
    "ts",
    "finding_id",
    "category",
    "class",
    "severity",
    "status",
    "response_type",
    "round",
    "first_round",
    "moved_from_decision",
}
FORBIDDEN_LINE_KEYS = {"claim", "snippet", "evidence", "reason", "trigger", "expected"}


@pytest.mark.parametrize("verb", DECIDE)
def test_fnd15_open_decide_sets_status_disposition_and_response_type(verb: str) -> None:
    state = _marked_state(snippet="  x  =  1 ")
    new_state, line, message = apply_mark(state, "F1", verb, "because", NOW)
    f = _finding(new_state)
    assert f["status"] == verb
    assert f["disposition"] == {
        "reason": "because",
        "at": NOW,
        "snippet_hash": sha(norm_snippet("x = 1")),
    }
    assert f["response_type"] == "agent_can_fix"
    assert line is not None
    assert LINE_KEYS <= set(line)
    assert not FORBIDDEN_LINE_KEYS & set(line)
    assert (line["finding_id"], line["status"], line["response_type"]) == (
        "F1",
        verb,
        "agent_can_fix",
    )
    assert (line["ts"], line["round"], line["first_round"]) == (NOW, 2, 1)
    assert "F1" in message
    assert verb in message


@pytest.mark.parametrize(
    ("overrides", "response_type"),
    [
        ({"severity": "nit"}, "nit"),
        ({"needs_decision": {"criterion": 1}}, "needs_decision"),
        ({"verdict": "uncertain"}, "uncertain"),
        ({"origin": "pre_existing"}, "pre_existing"),
    ],
)
def test_fnd15_response_type_is_the_section_before_the_change(
    overrides: dict, response_type: str
) -> None:
    state = _marked_state(**overrides)
    _, line, _ = apply_mark(state, "F1", "wontfix", "r", NOW)
    assert line is not None
    assert line["response_type"] == response_type


def test_fnd15_outcome_line_class_is_capped_at_80_chars() -> None:
    state = _marked_state(**{"class": "c" * 120})
    _, line, _ = apply_mark(state, "F1", "wontfix", "r", NOW)
    assert line is not None
    assert len(line["class"]) <= 80


def test_fnd15_open_open_is_a_noop() -> None:
    state = _marked_state()
    before = copy.deepcopy(state)
    new_state, line, message = apply_mark(state, "F1", "open", None, NOW)
    assert new_state == before
    assert line is None
    assert message == "F1 is already open"


def test_fnd15_open_fix_clears_needs_decision() -> None:
    state = _marked_state(needs_decision={"criterion": 1, "before": "a", "after": "b"})
    new_state, line, _ = apply_mark(state, "F1", "fix", None, NOW)
    assert line is None
    f = _finding(new_state)
    assert f["needs_decision"] is None
    assert f["moved_from_decision"] is True
    assert f["status"] == "open"


def test_fnd15_open_fix_without_needs_decision_is_refused() -> None:
    with pytest.raises(ValueError, match=r'^F1 is not in "needs your decision"$'):
        apply_mark(_marked_state(), "F1", "fix", None, NOW)


@pytest.mark.parametrize("verb", DECIDE)
def test_fnd15_fixed_decide_uses_response_type_fixed(verb: str) -> None:
    state = _marked_state(status="fixed")
    new_state, line, _ = apply_mark(state, "F1", verb, "r", NOW)
    f = _finding(new_state)
    assert f["status"] == verb
    assert f["response_type"] == "fixed"
    assert line is not None
    assert line["response_type"] == "fixed"


def test_fnd15_fixed_open_reopens_and_clears_reopen_round() -> None:
    state = _marked_state(status="fixed", reopen_round=2)
    new_state, _, _ = apply_mark(state, "F1", "open", None, NOW)
    f = _finding(new_state)
    assert f["status"] == "open"
    assert f["reopen_round"] is None


def test_fnd15_fixed_fix_is_refused() -> None:
    with pytest.raises(ValueError, match=r"^F1 is fixed, not open$"):
        apply_mark(_marked_state(status="fixed"), "F1", "fix", None, NOW)


@pytest.mark.parametrize("old", DECIDE)
@pytest.mark.parametrize("verb", DECIDE)
def test_fnd15_redecide_replaces_status_and_disposition(old: str, verb: str) -> None:
    disposition = {"reason": "old", "at": "2026-10-01T00:00:00Z", "snippet_hash": "h"}
    state = _marked_state(status=old, disposition=disposition)
    new_state, line, _ = apply_mark(state, "F1", verb, "new reason", NOW)
    f = _finding(new_state)
    assert f["status"] == verb
    assert f["disposition"]["reason"] == "new reason"
    assert f["disposition"]["at"] == NOW
    assert line is not None
    assert line["status"] == verb


@pytest.mark.parametrize("old", DECIDE)
def test_fnd15_decided_open_clears_disposition_and_reopen_round(old: str) -> None:
    disposition = {"reason": "old", "at": "2026-10-01T00:00:00Z", "snippet_hash": "h"}
    state = _marked_state(status=old, disposition=disposition, reopen_round=2)
    new_state, _, _ = apply_mark(state, "F1", "open", None, NOW)
    f = _finding(new_state)
    assert f["status"] == "open"
    assert f["disposition"] is None
    assert f["reopen_round"] is None


@pytest.mark.parametrize("old", DECIDE)
def test_fnd15_decided_fix_is_refused(old: str) -> None:
    with pytest.raises(ValueError, match=rf"^F1 is {old}, not open$"):
        apply_mark(_marked_state(status=old), "F1", "fix", None, NOW)


# --- FND-16 rule_suggestions --------------------------------------------------------------------

REPO = "https://host/o/r.git"


def _wrong(cls: str, repo: str = REPO, status: str = "wrong") -> dict:
    return {"repo": repo, "status": status, "class": cls}


def test_fnd16_three_wrong_in_one_class_gives_a_suggestion() -> None:
    out = rule_suggestions([_wrong("float rounding")] * 3, REPO, set())
    assert len(out) == 1
    assert out[0]["class"] == "float rounding"
    assert out[0]["text"] == (
        'Rule suggestion: "float rounding" marked wrong 3× in this repo. '
        "A REVIEW.md line such as: Do not report float rounding."
    )


def test_fnd16_two_are_not_enough() -> None:
    assert rule_suggestions([_wrong("float rounding")] * 2, REPO, set()) == []


def test_fnd16_similar_classes_group_greedily_by_080_ratio() -> None:
    outcomes = [
        _wrong("missing null check on input"),
        _wrong("missing null check on inputs"),
        _wrong("missing null-check on input"),
    ]
    out = rule_suggestions(outcomes, REPO, set())
    assert len(out) == 1
    assert out[0]["class"] == "missing null check on input"
    assert "marked wrong 3×" in out[0]["text"]


def test_fnd16_dissimilar_classes_do_not_group() -> None:
    outcomes = [_wrong("float rounding"), _wrong("sql injection"), _wrong("float rounding")]
    assert rule_suggestions(outcomes, REPO, set()) == []


def test_fnd16_other_repo_and_other_status_are_ignored() -> None:
    outcomes = [
        _wrong("float rounding"),
        _wrong("float rounding", repo="https://host/o/other.git"),
        _wrong("float rounding", status="wontfix"),
        _wrong("float rounding", status="fixed"),
        _wrong("float rounding"),
    ]
    assert rule_suggestions(outcomes, REPO, set()) == []


def test_fnd16_once_only_per_class() -> None:
    outcomes = [_wrong("float rounding")] * 4
    assert rule_suggestions(outcomes, REPO, {"float rounding"}) == []


def test_fnd16_two_groups_each_suggested() -> None:
    outcomes = [_wrong("float rounding")] * 3 + [_wrong("sql injection")] * 4
    out = rule_suggestions(outcomes, REPO, {"unrelated"})
    assert [o["class"] for o in out] == ["float rounding", "sql injection"]
    assert "marked wrong 4×" in out[1]["text"]


# --- FND-17 snippet_present ---------------------------------------------------------------------


def _h(snippet: str) -> str:
    return hashlib.sha256(norm_snippet(snippet).encode()).hexdigest()


def test_fnd17_present_window_of_consecutive_normalised_lines() -> None:
    assert snippet_present(FILE, _h("x = 1\ny = 2"), 2)


def test_fnd17_present_ignores_indentation_blank_lines_and_position() -> None:
    moved = "z = 0\n\n\n        x   = 1\n   y = 2\n"
    assert snippet_present(moved, _h("x = 1\ny = 2"), 2)


def test_fnd17_absent_when_lines_are_separated_or_changed() -> None:
    assert not snippet_present("x = 1\nq = 9\ny = 2\n", _h("x = 1\ny = 2"), 2)
    assert not snippet_present("x = 2\ny = 2\n", _h("x = 1\ny = 2"), 2)


def test_fnd17_missing_file_is_false() -> None:
    assert not snippet_present(None, _h("x = 1"), 1)


def test_fnd17_window_size_must_match() -> None:
    assert not snippet_present(FILE, _h("x = 1\ny = 2"), 1)
    assert not snippet_present(FILE, _h("x = 1\ny = 2"), 3)


def test_fnd17_cyrillic_and_single_line() -> None:
    assert snippet_present("# a\n  если   баланс\n", _h("если баланс"), 1)


def test_fnd17_file_shorter_than_window() -> None:
    assert not snippet_present("x = 1\n", _h("x = 1\ny = 2"), 2)


# --- FND-18 recheck_outcome ---------------------------------------------------------------------

RECHECK_TABLE = [
    # no verdict returned: stays open, unchanged
    ("all2", [N, N], None, True, ("open", None)),
    ("all2", [N, N], None, False, ("open", None)),
    ("maj3", [N, N, N], None, True, ("open", None)),
    # at least one holds: stays open, verdict from keep_outcome
    ("all2", [T, T], None, True, ("open", "confirmed")),
    ("all2", [T, T], None, False, ("open", "confirmed")),
    ("all2", [T, N], None, True, ("open", "uncertain")),
    ("all2", [T, F], None, True, ("open", "uncertain")),
    ("all2", [F, T], None, False, ("open", "uncertain")),
    ("all2_tiebreak", [T, F], T, True, ("open", "confirmed")),
    ("all2_tiebreak", [T, F], F, True, ("open", "uncertain")),
    ("all2_tiebreak", [T, F], N, False, ("open", "uncertain")),
    ("maj3", [T, T, F], None, True, ("open", "confirmed")),
    ("maj3", [T, F, F], None, True, ("open", "uncertain")),
    # all returned refute, code moved: fixed
    ("all2", [F, F], None, True, ("fixed", None)),
    ("all2", [F, N], None, True, ("fixed", None)),
    ("maj3", [F, F, F], None, True, ("fixed", None)),
    ("all2_tiebreak", [F, F], None, True, ("fixed", None)),
    # all returned refute, code unchanged: stays open, uncertain
    ("all2", [F, F], None, False, ("open", "uncertain")),
    ("all2", [N, F], None, False, ("open", "uncertain")),
    ("maj3", [F, F, F], None, False, ("open", "uncertain")),
    ("all2_tiebreak", [F, F], None, False, ("open", "uncertain")),
]


@pytest.mark.parametrize(("rule", "votes", "tiebreak", "moved", "expected"), RECHECK_TABLE)
def test_fnd18_recheck_outcome_table(
    rule: str,
    votes: list[bool | None],
    tiebreak: bool | None,
    moved: bool,
    expected: tuple[str, str | None],
) -> None:
    status, verdict = recheck_outcome(rule, [v(h) for h in votes], v(tiebreak), moved)
    assert status == expected[0]
    if expected[0] == "open":
        assert verdict == expected[1]


# --- merge_round: FND-6/7/8/9/10/11/12/18, ST-6 -------------------------------------------------

FILE_A = "def f(items):\n    # init\n    x = 1\n    return x\n"  # `x = 1` on line 3
FILE_A2 = "def f(items):\n    x = compute(a, b, c)\n    y = 2\n"  # `x = compute(a, b, c)` line 2
FORBIDDEN_WORDS = ("claim", "snippet", "evidence", "reason")


def ctx(**kw: Any) -> MergeContext:
    base: dict[str, Any] = {
        "now": NOW,
        "file_texts": {"src/a.py": FILE_A},
        "ranges": {"src/a.py": [(1, 50)]},
        "file_ids": {"src/a.py": "fid-1"},
        "intent_texts": [],
    }
    base.update(kw)
    return MergeContext(**base)


def merge(
    state: dict,
    plan: dict,
    cands: list[dict],
    verdicts: list[dict],
    *,
    missing: list[dict] | None = None,
    dropped: list[dict] | None = None,
    log: list[str] | None = None,
    context: MergeContext | None = None,
) -> MergeOutcome:
    result = make_result(
        plan,
        cands,
        verdicts,
        missing=missing or [],
        dropped=dropped or [],
        log=log or [],
        checksum=False,
    )
    return merge_round(state, plan, result, context or ctx())


def confirmed(cid: str, **kw: Any) -> list[dict]:
    return full_votes(cid, [True, True], **kw)


def fresh_state() -> dict:
    return make_state(rounds=[])


def round2_state(*findings: dict, rejected: list[dict] | None = None) -> dict:
    return make_state(list(findings), rounds=[make_round(1)], rejected=rejected or [])


def rej_entry(snippet: str = "x = 1", rnd: int = 1) -> dict:
    norm = norm_snippet(snippet)
    return {
        "fingerprint": fingerprint("logic", "src/a.py", "f", snippet),
        "category": "logic",
        "class": "off-by-one",
        "path": "src/a.py",
        "symbol": "f",
        "line": 3,
        "claim": "x starts at the wrong value",
        "snippet_hash": sha(norm),
        "snippet_lines": len(norm.splitlines()),
        "round": rnd,
    }


def test_fnd10_new_confirmed_item_creates_a_finding() -> None:
    state = fresh_state()
    merge(state, make_plan(), [candidate("N1.1", line=10)], confirmed("N1.1"))
    assert len(state["findings"]) == 1
    f = state["findings"][0]
    assert f["id"] == "F1"
    assert f["fingerprint"] == fingerprint("logic", "src/a.py", "f", "x = 1")
    assert (f["category"], f["class"]) == ("logic", "off-by-one")
    assert (f["status"], f["verdict"], f["severity"]) == ("open", "confirmed", "important")
    assert f["severity_votes"] == [
        {"model": "sonnet", "severity": "important", "reason": "reason"},
        {"model": "sonnet", "severity": "important", "reason": "reason"},
    ]
    assert f["origin"] == "introduced"
    assert f["anchor"] == {"path": "src/a.py", "line": 3, "symbol": "f", "snippet": "x = 1"}
    assert f["anchor_file_id"] == "fid-1"
    assert (f["claim"], f["trigger"]) == (
        "x starts at the wrong value",
        "call f with an empty list",
    )
    assert (f["evidence"], f["expected"]) == ("a.py:10 sets x = 1", "x starts at 0")
    assert (f["first_round"], f["last_seen_round"]) == (1, 1)
    assert f["disposition"] is None
    assert f["needs_decision"] is None
    assert f["response_type"] is None
    assert f["reopen_round"] is None
    assert f["moved_from_decision"] is False
    assert f["hidden_reason"] is None
    assert state["next_id"] == 2


def test_fnd10_ids_follow_next_id_and_candidate_order() -> None:
    state = fresh_state()
    state["next_id"] = 7
    cands = [candidate("N1.1"), candidate("N1.2", snippet="return x", symbol="g")]
    merge(state, make_plan(), cands, confirmed("N1.1") + confirmed("N1.2"))
    assert [f["id"] for f in state["findings"]] == ["F7", "F8"]
    assert state["findings"][0]["anchor"]["symbol"] == "f"
    assert state["next_id"] == 9


def test_st6_state_header_and_round_entry() -> None:
    state = fresh_state()
    plan = make_plan(file_ids={"src/a.py": "fid-1"})
    stats = {"agents_started": 7, "agents_returned": 6, "finders_null": 0, "verifiers_null": 1}
    result = make_result(plan, [candidate("N1.1")], confirmed("N1.1"), stats=stats, checksum=False)
    outcome = merge_round(state, plan, result, ctx())
    assert state["round"] == 1
    assert state["last_plan_id"] == "plan-1"
    assert state["head_sha"] == plan["head_sha"]
    assert state["tree_sha"] == plan["tree_sha"]
    assert state["change_id"] == plan["change_id"]
    assert state["file_ids"] == {"src/a.py": "fid-1"}
    assert state["rounds"] == [outcome.round_entry]
    e = outcome.round_entry
    assert (e["n"], e["level"], e["plan_id"]) == (1, "low", "plan-1")
    assert e["created_at"] == plan["created_at"]
    assert e["merged_at"] == NOW
    assert (e["head_sha"], e["tree_sha"], e["change_id"]) == (
        plan["head_sha"],
        plan["tree_sha"],
        plan["change_id"],
    )
    assert e["scope_kind"] == "full"
    assert e["files_in_scope"] == 1
    assert (e["agents_started"], e["agents_returned"]) == (7, 6)
    assert e["candidates"] == 1
    assert e["dedup_dropped"] == 0
    assert (e["kept"], e["rejected"], e["uncertain"]) == (1, 0, 0)
    assert e["fixed"] == []
    assert e["held_back"] == {
        "decided_suppressed": 0,
        "rejected_suppressed": 0,
        "outside_scope": 0,
        "duplicate_in_round": 0,
    }


def test_st6_dedup_dropped_and_candidates_are_counted_from_the_result() -> None:
    state = fresh_state()
    cands = [candidate("N1.1"), candidate("N1.2", snippet="y = 2", symbol="g")]
    dropped = [{"id": "N2.1", "dup_of": "N1.1"}, {"id": "N2.2", "dup_of": "N1.2"}]
    out = merge(
        state,
        make_plan(),
        cands,
        confirmed("N1.1") + confirmed("N1.2"),
        dropped=dropped,
        log=["l1"],
    )
    assert out.round_entry["candidates"] == 2
    assert out.round_entry["dedup_dropped"] == 2
    assert out.dropped == dropped
    assert out.log == ["l1"]


def test_fnd7_severity_split_is_counted_and_important_wins() -> None:
    state = fresh_state()
    votes = [
        verdict("N1.1", True, slot=0, severity="important"),
        verdict("N1.1", True, slot=1, severity="nit"),
    ]
    out = merge(state, make_plan(), [candidate("N1.1")], votes)
    f = state["findings"][0]
    assert f["severity"] == "important"
    assert [sv["severity"] for sv in f["severity_votes"]] == ["important", "nit"]
    assert out.round_entry["severity_splits"] == 1


def test_fnd7_all_nit_votes_make_a_nit() -> None:
    state = fresh_state()
    merge(state, make_plan(), [candidate("N1.1")], confirmed("N1.1", severity="nit"))
    assert state["findings"][0]["severity"] == "nit"


def test_fnd6_uncertain_item_is_kept_as_uncertain_with_lost_vote() -> None:
    state = fresh_state()
    holds: list[bool | None] = [True, None]
    out = merge(
        state,
        make_plan(),
        [candidate("N1.1")],
        full_votes("N1.1", holds),
        missing=missing_rows("N1.1", holds),
    )
    f = state["findings"][0]
    assert f["verdict"] == "uncertain"
    assert f["status"] == "open"
    assert len(f["severity_votes"]) == 1
    assert out.round_entry["uncertain"] == 1
    assert out.round_entry["kept"] == 0
    assert out.round_entry["lost_votes"] == 1
    assert out.round_entry["rejected"] == 0


def test_fnd6_no_vote_at_all_is_uncertain_never_rejected() -> None:
    state = fresh_state()
    holds: list[bool | None] = [None, None]
    out = merge(
        state,
        make_plan(),
        [candidate("N1.1")],
        [],
        missing=missing_rows("N1.1", holds),
    )
    assert len(state["findings"]) == 1
    assert state["findings"][0]["verdict"] == "uncertain"
    assert state["rejected"] == []
    assert out.round_entry["lost_votes"] == 2


def test_fnd10_rejected_item_goes_to_rejected_list() -> None:
    state = fresh_state()
    cand = candidate("N1.1", snippet="  x  =  1 ")
    out = merge(state, make_plan(), [cand], full_votes("N1.1", [False, False]))
    assert state["findings"] == []
    assert len(state["rejected"]) == 1
    r = state["rejected"][0]
    assert r["fingerprint"] == fingerprint("logic", "src/a.py", "f", "x = 1")
    assert (r["category"], r["class"], r["path"], r["symbol"]) == (
        "logic",
        "off-by-one",
        "src/a.py",
        "f",
    )
    assert r["claim"] == "x starts at the wrong value"
    assert r["snippet_hash"] == sha("x = 1")
    assert r["snippet_lines"] == 1
    assert r["round"] == 1
    assert out.round_entry["rejected"] == 1
    assert out.round_entry["rejected_ids"] == ["N1.1"]
    assert len(out.rejected) == 1
    assert out.rejected[0]["candidate"]["id"] == "N1.1"
    assert len(out.rejected[0]["votes"]) == 2


def test_fnd10_rejected_snippet_lines_counts_normalised_lines() -> None:
    state = fresh_state()
    cand = candidate("N1.1", snippet="a = 1\n\n  b = 2\n")
    merge(state, make_plan(), [cand], full_votes("N1.1", [False, False]))
    assert state["rejected"][0]["snippet_lines"] == 2
    assert state["rejected"][0]["snippet_hash"] == sha("a = 1\nb = 2")


def test_fnd10_same_fingerprint_rejected_again_only_updates_round() -> None:
    old = rej_entry(rnd=1)
    state = round2_state(rejected=[old])
    merge(state, make_plan(round_n=2), [candidate("N1.1")], full_votes("N1.1", [False, False]))
    assert len(state["rejected"]) == 1
    assert state["rejected"][0]["round"] == 2
    assert state["rejected"][0]["fingerprint"] == old["fingerprint"]


def test_fnd10_confirmed_match_with_open_finding_refreshes_and_keeps_fingerprint() -> None:
    f = fnd("F1", line=99, anchor_file_id="old-id")
    state = round2_state(f)
    fp = f["fingerprint"]
    merge(state, make_plan(round_n=2), [candidate("N1.1", line=99)], confirmed("N1.1"))
    assert len(state["findings"]) == 1
    g = state["findings"][0]
    assert g["fingerprint"] == fp
    assert g["last_seen_round"] == 2
    assert g["first_round"] == 1
    assert g["anchor"]["line"] == 3
    assert g["anchor_file_id"] == "fid-1"
    assert g["status"] == "open"
    assert state["next_id"] == 2


def test_fnd10_fuzzy_match_refreshes_snippet_but_not_fingerprint() -> None:
    f = fnd("F1", snippet="x = compute(a, b)")
    fp = f["fingerprint"]
    state = round2_state(f)
    cand = candidate("N1.1", snippet="x = compute(a, b, c)")
    merge(
        state,
        make_plan(round_n=2),
        [cand],
        confirmed("N1.1"),
        context=ctx(file_texts={"src/a.py": FILE_A2}),
    )
    assert len(state["findings"]) == 1
    g = state["findings"][0]
    assert g["fingerprint"] == fp
    assert g["anchor"]["snippet"] == "x = compute(a, b, c)"
    assert g["anchor"]["line"] == 2
    assert g["last_seen_round"] == 2


def test_fnd10_fixed_finding_reraised_is_reopened() -> None:
    state = round2_state(fnd("F1", status="fixed"))
    out = merge(state, make_plan(round_n=2), [candidate("N1.1")], confirmed("N1.1"))
    g = state["findings"][0]
    assert g["status"] == "open"
    assert g["last_seen_round"] == 2
    assert out.round_entry["reopened"] == ["F1"]
    assert len(state["findings"]) == 1


def _decided(status: str, snippet: str = "x = compute(a, b)", **kw: Any) -> dict:
    disposition = {
        "reason": "r",
        "at": "2026-10-20T00:00:00Z",
        "snippet_hash": sha(norm_snippet(snippet)),
    }
    return fnd("F1", snippet=snippet, status=status, disposition=disposition, **kw)


@pytest.mark.parametrize("status", ["intentional", "wontfix", "wrong", "superseded"])
def test_fnd11_decided_reraised_with_changed_snippet_reopens_once(status: str) -> None:
    state = round2_state(_decided(status))
    cand = candidate("N1.1", snippet="x = compute(a, b, c)")
    out = merge(
        state,
        make_plan(round_n=2),
        [cand],
        confirmed("N1.1"),
        context=ctx(file_texts={"src/a.py": FILE_A2}),
    )
    g = state["findings"][0]
    assert g["reopen_round"] == 2
    assert g["status"] == status
    assert len(state["findings"]) == 1
    assert out.round_entry["held_back"]["decided_suppressed"] == 0
    assert section_of(g, 2) == "reopen"


def test_fnd11_second_reraise_is_suppressed() -> None:
    state = round2_state(_decided("wontfix", reopen_round=2))
    state["rounds"].append(make_round(2))
    state["round"] = 2
    cand = candidate("N1.1", snippet="x = compute(a, b, c)")
    out = merge(
        state,
        make_plan(round_n=3),
        [cand],
        confirmed("N1.1"),
        context=ctx(file_texts={"src/a.py": FILE_A2}),
    )
    g = state["findings"][0]
    assert g["reopen_round"] == 2
    assert out.round_entry["held_back"]["decided_suppressed"] == 1
    assert section_of(g, 3) is None


def test_fnd11_reraise_with_unchanged_snippet_is_suppressed() -> None:
    state = round2_state(_decided("intentional"))
    out = merge(
        state,
        make_plan(round_n=2),
        [candidate("N1.1", snippet="x = compute(a, b)")],
        confirmed("N1.1"),
        context=ctx(file_texts={"src/a.py": "x = compute(a, b)\n"}),
    )
    g = state["findings"][0]
    assert g["reopen_round"] is None
    assert g["status"] == "intentional"
    assert out.round_entry["held_back"]["decided_suppressed"] == 1


def test_fnd11_no_reopen_without_a_reraise() -> None:
    state = round2_state(_decided("wontfix"))
    merge(state, make_plan(round_n=2), [], [])
    assert state["findings"][0]["reopen_round"] is None
    assert state["findings"][0]["status"] == "wontfix"


def test_fnd10_rejected_entry_suppresses_exact_fingerprint_with_unchanged_snippet() -> None:
    state = round2_state(rejected=[rej_entry()])
    out = merge(state, make_plan(round_n=2), [candidate("N1.1")], confirmed("N1.1"))
    assert state["findings"] == []
    assert len(state["rejected"]) == 1
    assert out.round_entry["held_back"]["rejected_suppressed"] == 1


def test_fnd10_changed_snippet_gives_a_new_item_despite_rejected_entry() -> None:
    state = round2_state(rejected=[rej_entry("x = compute(a, b)")])
    cand = candidate("N1.1", snippet="x = compute(a, b, c)")
    out = merge(
        state,
        make_plan(round_n=2),
        [cand],
        confirmed("N1.1"),
        context=ctx(file_texts={"src/a.py": FILE_A2}),
    )
    assert [f["id"] for f in state["findings"]] == ["F1"]
    assert out.round_entry["held_back"]["rejected_suppressed"] == 0


@pytest.mark.parametrize(
    "second_snippet", ["x = 1", "x = 1\n", "  x  =  1"], ids=["same", "newline", "indent"]
)
def test_fnd10_in_round_duplicate_makes_one_finding(second_snippet: str) -> None:
    state = fresh_state()
    cands = [candidate("N1.1"), candidate("N2.1", finder=2, snippet=second_snippet)]
    out = merge(state, make_plan(), cands, confirmed("N1.1") + confirmed("N2.1"))
    assert len(state["findings"]) == 1
    assert out.round_entry["held_back"]["duplicate_in_round"] == 1
    assert state["next_id"] == 2


def test_fnd10_in_round_fuzzy_duplicate_makes_one_finding() -> None:
    state = fresh_state()
    cands = [
        candidate("N1.1", snippet="x = compute(a, b)"),
        candidate("N2.1", finder=2, snippet="x = compute(a, b, c)"),
    ]
    out = merge(state, make_plan(), cands, confirmed("N1.1") + confirmed("N2.1"))
    assert len(state["findings"]) == 1
    assert out.round_entry["held_back"]["duplicate_in_round"] == 1


def test_fnd10_distinct_items_are_not_duplicates() -> None:
    state = fresh_state()
    cands = [candidate("N1.1"), candidate("N1.2", symbol="g", snippet="return x")]
    out = merge(state, make_plan(), cands, confirmed("N1.1") + confirmed("N1.2"))
    assert len(state["findings"]) == 2
    assert out.round_entry["held_back"]["duplicate_in_round"] == 0


def test_fnd12_round3_finding_outside_scope_is_hidden() -> None:
    """FND-12 keys on `scope.kind == "since"` (RPT-18); round 3 defaults to `since`."""
    state = make_state(rounds=[make_round(1), make_round(2)])
    plan = make_plan(round_n=3, scope_files=["src/b.py"])
    out = merge(state, plan, [candidate("N1.1")], confirmed("N1.1"))
    f = state["findings"][0]
    assert f["hidden_reason"] == "outside_scope"
    assert out.round_entry["held_back"]["outside_scope"] == 1
    assert section_of(f, 3) is None


@pytest.mark.parametrize("round_n", [1, 2])
def test_fnd12_early_rounds_never_hide(round_n: int) -> None:
    state = make_state(rounds=[make_round(i) for i in range(1, round_n)])
    plan = make_plan(round_n=round_n, scope_files=["src/b.py"])
    merge(state, plan, [candidate("N1.1")], confirmed("N1.1"))
    assert state["findings"][0]["hidden_reason"] is None


def test_fnd12_since_scope_in_round_two_also_hides() -> None:
    """RPT-18: a round-2 `--incremental` round (`since` scope) hides like round 3 used to."""
    state = make_state(rounds=[make_round(1)])
    plan = make_plan(round_n=2, scope_files=["src/b.py"], scope_kind="since")
    out = merge(state, plan, [candidate("N1.1")], confirmed("N1.1"))
    f = state["findings"][0]
    assert f["hidden_reason"] == "outside_scope"
    assert out.round_entry["held_back"]["outside_scope"] == 1


def test_fnd12_full_scope_in_round_three_never_hides() -> None:
    """RPT-18: a `--full` round >= 3 (`full` scope) no longer hides, same as rounds 1-2."""
    state = make_state(rounds=[make_round(1), make_round(2)])
    plan = make_plan(round_n=3, scope_files=["src/b.py"], scope_kind="full")
    merge(state, plan, [candidate("N1.1")], confirmed("N1.1"))
    assert state["findings"][0]["hidden_reason"] is None


def test_fnd12_finding_in_scope_is_not_hidden_in_round3() -> None:
    state = make_state(rounds=[make_round(1), make_round(2)])
    plan = make_plan(round_n=3, scope_files=["src/a.py"])
    merge(state, plan, [candidate("N1.1")], confirmed("N1.1"))
    assert state["findings"][0]["hidden_reason"] is None


def test_fnd12_hidden_reason_cleared_when_a_later_scope_contains_the_path() -> None:
    hidden = fnd("F1", hidden_reason="outside_scope")
    state = make_state([hidden], rounds=[make_round(1), make_round(2), make_round(3)])
    merge(state, make_plan(round_n=4, scope_files=["src/a.py"]), [], [])
    assert state["findings"][0]["hidden_reason"] is None


def test_fnd12_hidden_reason_kept_while_scope_lacks_the_path() -> None:
    hidden = fnd("F1", hidden_reason="outside_scope")
    state = make_state([hidden], rounds=[make_round(1), make_round(2), make_round(3)])
    merge(state, make_plan(round_n=4, scope_files=["src/b.py"]), [], [])
    assert state["findings"][0]["hidden_reason"] == "outside_scope"


def test_fnd9_origin_introduced_when_located_line_is_in_a_changed_range() -> None:
    state = fresh_state()
    merge(state, make_plan(), [candidate("N1.1", line=99)], confirmed("N1.1"))
    assert state["findings"][0]["origin"] == "introduced"
    assert state["findings"][0]["anchor"]["line"] == 3


def test_fnd9_origin_uses_the_located_line_not_the_reported_one() -> None:
    state = fresh_state()
    context = ctx(ranges={"src/a.py": [(50, 60)]})
    merge(state, make_plan(), [candidate("N1.1", line=55)], confirmed("N1.1"), context=context)
    assert state["findings"][0]["origin"] == "pre_existing"


def test_fnd9_origin_broken_by_change() -> None:
    state = fresh_state()
    cand = candidate("N1.1", broken_by={"path": "src/b.py", "line": 6})
    context = ctx(ranges={"src/a.py": [(50, 60)], "src/b.py": [(5, 8)]})
    merge(state, make_plan(), [cand], confirmed("N1.1"), context=context)
    assert state["findings"][0]["origin"] == "broken_by_change"


def test_fnd9_origin_reported_line_used_when_snippet_is_not_found() -> None:
    state = fresh_state()
    cand = candidate("N1.1", line=12, snippet="not in file")
    context = ctx(ranges={"src/a.py": [(12, 12)]})
    merge(state, make_plan(), [cand], confirmed("N1.1"), context=context)
    f = state["findings"][0]
    assert f["anchor"]["line"] == 12
    assert f["origin"] == "introduced"


def _doc_plan(round_n: int, sections: list[str], scope_kind: str | None = None) -> dict:
    return make_plan(
        round_n=round_n,
        mode="document",
        scope_files=["docs/spec.md"],
        sections=sections,
        scope_kind=scope_kind,
    )


def _doc_cand(symbol: str, **kw: Any) -> dict:
    return candidate(
        "N1.1", category="ambiguity", path="docs/spec.md", symbol=symbol, snippet="Do it.", **kw
    )


def _doc_ctx() -> MergeContext:
    return ctx(
        file_texts={"docs/spec.md": "# Intro\nDo it.\n"},
        ranges={},
        file_ids={"Intro": "h-intro", "Other": "h-other"},
    )


@pytest.mark.parametrize(
    ("round_n", "sections", "symbol", "note", "origin"),
    [
        (1, [], "Other", "", "in_scope"),
        (3, ["Intro"], "Intro", "", "in_scope"),
        (3, ["Intro"], "Other", "", "out_of_scope"),
        (1, [], "Intro", "outside-goal", "out_of_scope"),
        (3, ["Intro"], "Intro", "outside-goal", "out_of_scope"),
    ],
)
def test_doc5_document_origin(
    round_n: int, sections: list[str], symbol: str, note: str, origin: str
) -> None:
    """DOC-5 keys on `scope.kind == "since"` (RPT-18); `_doc_plan`'s default scope kind here
    still matches round <= 2 -> full, round >= 3 -> since."""
    state = make_state(rounds=[make_round(i, mode="document") for i in range(1, round_n)])
    state["mode"] = "document"
    merge(
        state,
        _doc_plan(round_n, sections),
        [_doc_cand(symbol, scope_note=note)],
        confirmed("N1.1"),
        context=_doc_ctx(),
    )
    assert state["findings"][0]["origin"] == origin


def test_doc5_since_scope_in_round_two_is_out_of_scope() -> None:
    """RPT-18: a round-2 `--incremental` round (`since` scope) finds unchanged sections out of
    scope, same as round 3 used to."""
    state = make_state(rounds=[make_round(1, mode="document")])
    state["mode"] = "document"
    merge(
        state,
        _doc_plan(2, ["Intro"], scope_kind="since"),
        [_doc_cand("Other")],
        confirmed("N1.1"),
        context=_doc_ctx(),
    )
    assert state["findings"][0]["origin"] == "out_of_scope"


def test_doc5_full_scope_in_round_three_is_in_scope() -> None:
    """RPT-18: a `--full` round >= 3 (`full` scope) treats every section as in scope."""
    state = make_state(rounds=[make_round(1, mode="document"), make_round(2, mode="document")])
    state["mode"] = "document"
    merge(
        state,
        _doc_plan(3, ["Intro"], scope_kind="full"),
        [_doc_cand("Other")],
        confirmed("N1.1"),
        context=_doc_ctx(),
    )
    assert state["findings"][0]["origin"] == "in_scope"


def test_st5_document_anchor_file_id_is_the_section_hash() -> None:
    state = fresh_state()
    state["mode"] = "document"
    merge(
        state,
        _doc_plan(1, []),
        [_doc_cand("Intro")],
        confirmed("N1.1"),
        context=_doc_ctx(),
    )
    assert state["findings"][0]["anchor_file_id"] == "h-intro"


def test_st5_code_anchor_file_id_is_empty_when_path_not_in_branch_diff() -> None:
    state = fresh_state()
    merge(state, make_plan(), [candidate("N1.1")], confirmed("N1.1"), context=ctx(file_ids={}))
    assert state["findings"][0]["anchor_file_id"] == ""


def test_fnd8_valid_flag_becomes_needs_decision() -> None:
    state = fresh_state()
    flagged = verdict(
        "N1.1", True, slot=0, needs_decision=nd(1, before="refund 100", after="refund 30")
    )
    plain = verdict("N1.1", True, slot=1)
    out = merge(state, make_plan(), [candidate("N1.1")], [flagged, plain])
    d = state["findings"][0]["needs_decision"]
    assert d["criterion"] == 1
    assert (d["before"], d["after"]) == ("refund 100", "refund 30")
    assert out.round_entry["decision_flags_dropped"] == 0
    assert out.round_entry["decision_flags"] == 1


def test_fnd8_invalid_flag_is_dropped_and_counted() -> None:
    state = fresh_state()
    flagged = verdict("N1.1", True, slot=0, needs_decision=nd(1, before="same", after="same"))
    out = merge(state, make_plan(), [candidate("N1.1")], [flagged, verdict("N1.1", True, slot=1)])
    assert state["findings"][0]["needs_decision"] is None
    assert out.round_entry["decision_flags_dropped"] == 1
    assert out.round_entry["decision_flags"] == 0


def test_fnd8_criterion_two_is_checked_against_intent_texts() -> None:
    quote = "must never double charge"
    ok_flag = verdict("N1.1", True, slot=0, needs_decision=nd(2, intent_quote=quote))
    state = fresh_state()
    merge(
        state,
        make_plan(),
        [candidate("N1.1")],
        [ok_flag, verdict("N1.1", True, slot=1)],
        context=ctx(intent_texts=["The system must  never double charge a customer."]),
    )
    assert state["findings"][0]["needs_decision"]["criterion"] == 2
    state = fresh_state()
    out = merge(state, make_plan(), [candidate("N1.1")], [ok_flag, verdict("N1.1", True, slot=1)])
    assert state["findings"][0]["needs_decision"] is None
    assert out.round_entry["decision_flags_dropped"] == 1


def test_fnd8_lowest_valid_criterion_wins_across_verdicts() -> None:
    c3 = nd(3, options=[{"label": "A", "observable": "x"}, {"label": "B", "observable": "y"}])
    votes = [
        verdict("N1.1", True, slot=0, needs_decision=c3),
        verdict("N1.1", True, slot=1, needs_decision=nd(1, before="a", after="b")),
    ]
    state = fresh_state()
    merge(state, make_plan(), [candidate("N1.1")], votes)
    assert state["findings"][0]["needs_decision"]["criterion"] == 1


def test_fnd8_applies_to_nits_too() -> None:
    flag = nd(1, before="a", after="b")
    votes = [
        verdict("N1.1", True, slot=0, severity="nit", needs_decision=flag),
        verdict("N1.1", True, slot=1, severity="nit"),
    ]
    state = fresh_state()
    merge(state, make_plan(), [candidate("N1.1")], votes)
    f = state["findings"][0]
    assert f["severity"] == "nit"
    assert f["needs_decision"] is not None


def _tiebreak_plan(round_n: int = 1, **kw: Any) -> dict:
    return make_plan(
        round_n=round_n,
        level="high",
        votes=("sonnet", "opus"),
        tiebreak="opus",
        keep_rule="all2_tiebreak",
        **kw,
    )


def _tb(item: str, holds: bool) -> dict:
    return verdict(item, holds, role="tiebreak", slot=0, model="opus")


def test_st6_disagreements_tiebreaks_and_overturns() -> None:
    state = fresh_state()
    cands = [
        candidate("N1.1"),
        candidate("N1.2", snippet="y = 2", symbol="g"),
        candidate("N1.3", snippet="z = 3", symbol="h"),
    ]
    votes = (
        full_votes("N1.1", [True, False])
        + [_tb("N1.1", True)]
        + full_votes("N1.2", [True, True])
        + full_votes("N1.3", [False, False])
    )
    out = merge(state, _tiebreak_plan(), cands, votes)
    e = out.round_entry
    assert e["disagreements"] == 1
    assert e["tiebreaks"] == 1
    assert e["tiebreak_overturns"] == 1
    assert (e["kept"], e["rejected"], e["uncertain"]) == (2, 1, 0)
    assert [f["id"] for f in state["findings"]] == ["F1", "F2"]


def test_st6_tiebreak_agreeing_with_last_vote_is_no_overturn() -> None:
    state = fresh_state()
    votes = full_votes("N1.1", [True, False]) + [_tb("N1.1", False)]
    out = merge(state, _tiebreak_plan(), [candidate("N1.1")], votes)
    assert out.round_entry["tiebreaks"] == 1
    assert out.round_entry["tiebreak_overturns"] == 0
    assert state["findings"] == []
    assert len(state["rejected"]) == 1


def test_fnd7_tiebreak_verdict_counts_as_confirming_for_severity() -> None:
    state = fresh_state()
    votes = [
        verdict("N1.1", True, slot=0, severity="nit"),
        verdict("N1.1", False, slot=1),
        verdict("N1.1", True, role="tiebreak", slot=0, model="opus", severity="important"),
    ]
    out = merge(state, _tiebreak_plan(), [candidate("N1.1")], votes)
    f = state["findings"][0]
    assert f["severity"] == "important"
    assert [sv["model"] for sv in f["severity_votes"]] == ["sonnet", "opus"]
    assert out.round_entry["severity_splits"] == 1


def test_rpt7_outcome_carries_votes_for_the_round_file() -> None:
    state = fresh_state()
    out = merge(state, make_plan(), [candidate("N1.1")], confirmed("N1.1"))
    assert len(out.votes["F1"]) == 2


# --- recheck through merge_round (FND-18) -------------------------------------------------------


def _recheck_state(**kw: Any) -> dict:
    return round2_state(fnd("F1", anchor_file_id="fid-1", **kw))


def _recheck(
    holds: list[bool | None],
    *,
    plan: dict | None = None,
    context: MergeContext | None = None,
    extra: list[dict] | None = None,
    **vote_kw: Any,
) -> tuple[dict, MergeOutcome]:
    state = vote_kw.pop("state", None) or _recheck_state()
    plan = plan or make_plan(round_n=2, recheck_ids=["F1"])
    verdicts = full_votes("F1", holds, kind="recheck", **vote_kw) + (extra or [])
    out = merge(
        state,
        plan,
        [],
        verdicts,
        missing=missing_rows("F1", holds),
        context=context,
    )
    return state, out


def test_fnd18_holds_keeps_open_confirmed_and_updates_last_seen() -> None:
    state, out = _recheck([True, True])
    f = state["findings"][0]
    assert (f["status"], f["verdict"], f["last_seen_round"]) == ("open", "confirmed", 2)
    assert out.round_entry["fixed"] == []
    assert out.outcome_lines == []


def test_fnd18_one_holder_among_refuters_is_uncertain_and_open() -> None:
    state, _ = _recheck([True, False])
    f = state["findings"][0]
    assert (f["status"], f["verdict"]) == ("open", "uncertain")


def test_fnd18_holds_raises_severity_to_the_maximum() -> None:
    state = round2_state(fnd("F1", severity="nit", anchor_file_id="fid-1"))
    state, _ = _recheck([True, True], state=state, severity="important")
    assert state["findings"][0]["severity"] == "important"


def test_fnd18_holds_never_lowers_severity() -> None:
    state, _ = _recheck([True, True], severity="nit")
    assert state["findings"][0]["severity"] == "important"


def test_fnd18_holds_refreshes_anchor_line_and_file_id() -> None:
    state = round2_state(fnd("F1", line=7, anchor_file_id="fid-1"))
    context = ctx(file_ids={"src/a.py": "fid-2"})
    state, _ = _recheck([True, True], state=state, context=context)
    f = state["findings"][0]
    assert f["anchor"]["line"] == 3
    assert f["anchor_file_id"] == "fid-2"


def test_fnd18_all_refute_with_snippet_gone_is_fixed() -> None:
    context = ctx(file_texts={"src/a.py": "def f():\n    pass\n"})
    state, out = _recheck([False, False], context=context)
    assert state["findings"][0]["status"] == "fixed"
    assert out.round_entry["fixed"] == ["F1"]
    assert len(out.outcome_lines) == 1
    line = out.outcome_lines[0]
    assert (line["finding_id"], line["status"], line["round"]) == ("F1", "fixed", 2)
    assert not set(FORBIDDEN_WORDS) & set(line)


def test_fnd18_all_refute_with_file_deleted_is_fixed() -> None:
    context = ctx(file_texts={"src/a.py": None})
    state, out = _recheck([False, False], context=context)
    assert state["findings"][0]["status"] == "fixed"
    assert out.round_entry["fixed"] == ["F1"]


def test_fnd18_all_refute_with_file_diff_id_changed_is_fixed() -> None:
    context = ctx(file_ids={"src/a.py": "fid-2"})
    state, out = _recheck([False, False], context=context)
    assert state["findings"][0]["status"] == "fixed"
    assert out.round_entry["fixed"] == ["F1"]


def test_fnd18_all_refute_with_unchanged_code_stays_open_uncertain() -> None:
    state, out = _recheck([False, False])
    f = state["findings"][0]
    assert (f["status"], f["verdict"]) == ("open", "uncertain")
    assert out.round_entry["fixed"] == []
    assert out.outcome_lines == []


def test_fnd18_one_refute_one_missing_counts_as_all_refute() -> None:
    context = ctx(file_texts={"src/a.py": None})
    state, _ = _recheck([False, None], context=context)
    assert state["findings"][0]["status"] == "fixed"


def test_fnd18_no_verdict_returned_leaves_the_finding_unchanged() -> None:
    state = _recheck_state()
    before = copy.deepcopy(state["findings"][0])
    state, out = _recheck([None, None], state=state, context=ctx(file_texts={"src/a.py": None}))
    assert state["findings"][0] == before
    assert out.round_entry["lost_votes"] == 2
    assert out.round_entry["fixed"] == []


def test_fnd18_tiebreak_holding_keeps_the_finding_confirmed() -> None:
    plan = _tiebreak_plan(round_n=2, recheck_ids=["F1"])
    extra = [_tb("F1", True)]
    extra[0]["kind"] = "recheck"
    state, _ = _recheck([True, False], plan=plan, extra=extra)
    assert (state["findings"][0]["status"], state["findings"][0]["verdict"]) == (
        "open",
        "confirmed",
    )


def test_fnd10_recheck_items_do_not_create_findings() -> None:
    state, _ = _recheck([True, True])
    assert len(state["findings"]) == 1
    assert state["next_id"] == 2


def test_rpt11_round_entry_carries_render_inputs() -> None:
    """RPT-11: merge_round writes nit_cap, intent_none, doc_path and empty suggestions."""
    plan = make_plan()
    plan["review_md"] = {"path": "verify/review-md-base.md", "nit_cap": 3}
    plan["intent"] = {"none": True, "sources": []}
    state = fresh_state()
    out = merge(
        state, plan, [candidate("N1.1")], confirmed("N1.1"), context=ctx(doc_path="docs/spec.md")
    )
    e = out.round_entry
    assert e["nit_cap"] == 3
    assert e["intent_none"] is True
    assert e["doc_path"] == "docs/spec.md"
    assert e["suggestions"] == []


def test_fnd8_flag_on_a_refuting_vote_is_ignored() -> None:
    """FND-8: only flags from holding verdicts of kept items count."""
    flag = nd(1, before="a", after="b")
    votes = [
        verdict("N1.1", True, slot=0),
        verdict("N1.1", False, slot=1, needs_decision=flag),
        _tb("N1.1", True),
    ]
    state = fresh_state()
    out = merge(state, _tiebreak_plan(), [candidate("N1.1")], votes)
    assert state["findings"][0]["needs_decision"] is None
    assert out.round_entry["decision_flags"] == 0
    assert out.round_entry["decision_flags_dropped"] == 0


def test_fnd8_flag_on_a_holding_tiebreak_counts() -> None:
    """FND-8: confirming verdicts include a holding tie-break."""
    flag = nd(1, before="a", after="b")
    votes = [
        verdict("N1.1", True, slot=0),
        verdict("N1.1", False, slot=1),
        verdict("N1.1", True, role="tiebreak", slot=0, model="opus", needs_decision=flag),
    ]
    state = fresh_state()
    out = merge(state, _tiebreak_plan(), [candidate("N1.1")], votes)
    assert state["findings"][0]["needs_decision"]["criterion"] == 1
    assert out.round_entry["decision_flags"] == 1


def test_fnd10_rejected_candidate_matching_an_open_finding_leaves_it_unchanged() -> None:
    """FND-10: outcome rejected -> rejected[] entry; the open finding is not touched."""
    f = fnd("F1")
    state = round2_state(f)
    before = copy.deepcopy(state["findings"][0])
    out = merge(
        state, make_plan(round_n=2), [candidate("N1.1")], full_votes("N1.1", [False, False])
    )
    assert state["findings"][0] == before
    assert len(state["findings"]) == 1
    assert len(state["rejected"]) == 1
    assert out.round_entry["rejected"] == 1


def test_fnd10_recheck_is_processed_before_new_items() -> None:
    """FND-10: F1 fixed by its re-check, then reopened by a matching confirmed new item."""
    state = round2_state(fnd("F1", anchor_file_id="fid-1"))
    plan = make_plan(round_n=2, recheck_ids=["F1"])
    verdicts = full_votes("F1", [False, False], kind="recheck") + confirmed("N1.1")
    out = merge(
        state,
        plan,
        [candidate("N1.1")],
        verdicts,
        context=ctx(file_ids={"src/a.py": "fid-2"}),
    )
    assert out.round_entry["fixed"] == ["F1"]
    assert out.round_entry["reopened"] == ["F1"]
    assert len(state["findings"]) == 1
    assert state["findings"][0]["status"] == "open"
    assert state["next_id"] == 2


def test_fnd10_decided_reopen_hit_refreshes_anchor_but_not_disposition_hash() -> None:
    f = _decided("wontfix", line=99, anchor_file_id="old-id")
    old_hash = f["disposition"]["snippet_hash"]
    state = round2_state(f)
    merge(
        state,
        make_plan(round_n=2),
        [candidate("N1.1", snippet="x = compute(a, b, c)")],
        confirmed("N1.1"),
        context=ctx(file_texts={"src/a.py": FILE_A2}),
    )
    g = state["findings"][0]
    assert g["reopen_round"] == 2
    assert g["anchor"]["line"] == 2
    assert g["anchor"]["snippet"] == "x = compute(a, b, c)"
    assert g["anchor_file_id"] == "fid-1"
    assert g["disposition"]["snippet_hash"] == old_hash


def test_fnd10_decided_suppressed_hit_refreshes_anchor_too() -> None:
    f = _decided("intentional", line=99, anchor_file_id="old-id")
    old_hash = f["disposition"]["snippet_hash"]
    state = round2_state(f)
    merge(
        state,
        make_plan(round_n=2),
        [candidate("N1.1", snippet="x = compute(a, b)")],
        confirmed("N1.1"),
        context=ctx(file_texts={"src/a.py": "x = compute(a, b)\n"}),
    )
    g = state["findings"][0]
    assert g["anchor"]["line"] == 1
    assert g["anchor_file_id"] == "fid-1"
    assert g["disposition"]["snippet_hash"] == old_hash


def test_fnd12_document_round3_outside_scope_is_out_of_scope_not_hidden() -> None:
    """FND-12 is code-only; documents use DOC-5."""
    state = make_state(rounds=[make_round(1), make_round(2)])
    state["mode"] = "document"
    merge(
        state,
        _doc_plan(3, ["Intro"]),
        [_doc_cand("Other")],
        confirmed("N1.1"),
        context=_doc_ctx(),
    )
    f = state["findings"][0]
    assert f["origin"] == "out_of_scope"
    assert f["hidden_reason"] is None


# --- code review R2 -----------------------------------------------------------------------------


def test_rpt15_lone_surrogates_are_replaced_before_hashing_and_writing() -> None:
    """RPT-15: lone surrogates in result strings become U+FFFD; the state serialises."""
    import json

    state = fresh_state()
    cand = candidate("N1.1", snippet="\ud800", claim="bad \udfff claim")
    merge(state, make_plan(), [cand], confirmed("N1.1"))
    f = state["findings"][0]
    assert f["anchor"]["snippet"] == "�"
    assert f["claim"] == "bad � claim"
    assert f["fingerprint"] == fingerprint("logic", "src/a.py", "f", "�")
    json.dumps(state).encode("utf-8")


def test_fnd7_empty_severity_is_ignored() -> None:
    """FND-7: an empty severity on a holding verdict neither splits nor adds a vote entry."""
    assert severity_of(_sev("important", "")) == ("important", False)
    state = fresh_state()
    votes = [verdict("N1.1", True, slot=0), verdict("N1.1", True, slot=1, severity="")]
    out = merge(state, make_plan(), [candidate("N1.1")], votes)
    assert len(state["findings"][0]["severity_votes"]) == 1
    assert out.round_entry["severity_splits"] == 0


def test_st6_overturn_compares_with_the_last_slot_and_skips_a_missing_one() -> None:
    """ST-6: the last slot's vote is the reference; a missing one means no overturn."""
    state = fresh_state()
    holds: list[bool | None] = [False, None]
    votes = full_votes("N1.1", holds) + [_tb("N1.1", True)]
    out = merge(
        state, _tiebreak_plan(), [candidate("N1.1")], votes, missing=missing_rows("N1.1", holds)
    )
    assert out.round_entry["tiebreaks"] == 1
    assert out.round_entry["tiebreak_overturns"] == 0


def test_fnd5_long_texts_are_still_compared() -> None:
    """FND-5: very long snippets do not break matching."""
    long_snippet = "x = 1 " * 3000
    f = fnd("F1", snippet=long_snippet)
    assert match(_cand(snippet=long_snippet), [f]) is not None
