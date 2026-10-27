"""Tests for `report` (SPECS RPT-1..RPT-9, FND-13/FND-14 rendering).

Report inputs beyond ST-4 are read from the latest `rounds[]` entry (RPT-11): `nit_cap`,
`intent_none`, `doc_path`, `suggestions`.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from helpers_pure import candidate, make_finding, make_round, make_state, verdict
from review_cycle.findings import MergeOutcome
from review_cycle.report import render_report, render_round_md, render_show, report_findings

DATA = Path(__file__).parent / "data" / "reports"


def assert_golden(actual: str, name: str) -> None:
    expected = (DATA / f"{name}.txt").read_text(encoding="utf-8")
    assert actual.rstrip("\n") == expected.rstrip("\n")


def f(fid: str, path: str, line: int, claim: str, **kw: Any) -> dict:
    return make_finding(fid, path=path, line=line, claim=claim, **kw)


def decision(criterion: int, **kw: Any) -> dict:
    base: dict[str, Any] = {
        "criterion": criterion,
        "before": "",
        "after": "",
        "intent_quote": "",
        "options": [],
    }
    base.update(kw)
    return base


CHARGE = f(
    "F4",
    "src/billing/charge.ts",
    142,
    "retry after a timeout charges twice",
    **{"class": "retries without idempotency key"},
)


def two_rounds(**last: Any) -> list[dict]:
    return [make_round(1), make_round(2, level="high", scope_kind="since", **last)]


# --- goldens ------------------------------------------------------------------------------------


def mixed_state() -> dict:
    refund = f(
        "F7",
        "src/billing/refund.ts",
        58,
        "refund of a partly paid order returns the full sum",
        trigger="order paid 30 of 100, user cancels → refund 100",
        evidence="refund.ts:58 takes order.total, not the paid sum (refund.ts:41)",
        needs_decision=decision(
            3,
            options=[
                {"label": "refund the paid sum", "observable": "refund 30"},
                {"label": "refuse partial refunds", "observable": "error"},
            ],
        ),
    )
    findings = [
        f("F1", "src/old.ts", 1, "old one", status="fixed"),
        f("F2", "src/old.ts", 2, "old two", status="fixed"),
        CHARGE,
        f(
            "F5",
            "src/billing/charge.ts",
            90,
            "save is not awaited",
            **{"class": "missing await"},
        ),
        refund,
        f("F10", "src/a.ts", 3, "unused import", severity="nit", first_round=2),
        f("F11", "src/b.ts", 9, "magic number", severity="nit", first_round=2),
        f("F12", "src/b.ts", 2, "typo in log message", severity="nit", first_round=2),
        f("F13", "src/billing/tax.ts", 12, "rounding uses float", origin="pre_existing"),
        f("F20", "src/h.ts", 1, "hidden one", hidden_reason="outside_scope"),
        f("F21", "src/h.ts", 2, "hidden two", hidden_reason="outside_scope"),
    ]
    rounds = two_rounds(agents_returned=9, rejected=6, fixed=["F1", "F2"], head_sha="9999999000")
    return make_state(findings, rounds)


def test_rpt_golden_mixed_report() -> None:
    """RPT-1..6: header, counts, closed/not-shown line, section order, item formats."""
    assert_golden(render_report(mixed_state()), "mixed")


def test_rpt_golden_nothing_to_fix() -> None:
    """RPT-3: `Nothing to fix.` when a + b + u = 0; round 1 header `vs <base>@<mb7>`."""
    state = make_state([], [make_round(1, level="low", agents_returned=4, rejected=2)])
    assert_golden(render_report(state), "nothing_to_fix")


def test_rpt_golden_unchanged_header() -> None:
    """RPT-1/RND-7: `No code change since round N` line, then the report re-rendered."""
    state = make_state([CHARGE], [make_round(1, level="high", agents_returned=9)])
    assert_golden(render_report(state, no_change_of=1), "unchanged")


def test_rpt_golden_document_mode() -> None:
    """RPT-1/RPT-4/DOC-5: `doc <path>` header, `Out of scope` instead of `Pre-existing`."""
    findings = [
        f(
            "F1",
            "docs/spec.md",
            12,
            "section Limits contradicts section Quotas",
            symbol="Limits",
            **{"class": "contradiction"},
        ),
        f(
            "F2",
            "docs/spec.md",
            40,
            "term used before it is defined",
            symbol="Terms",
            origin="out_of_scope",
        ),
    ]
    rounds = [make_round(1, level="low", agents_returned=4, doc_path="docs/spec.md")]
    state = make_state(findings, rounds, mode="document", target="doc-docs-spec-md")
    assert_golden(render_report(state), "doc_mode")


def test_rpt_golden_nit_cap_overflow() -> None:
    """FND-13/RPT-2/RPT-4: nits sorted first_round desc, path, line; cap shown; rest counted."""
    findings = [
        f("F1", "src/a.py", 5, "claim one", severity="nit", first_round=1),
        f("F2", "src/a.py", 9, "claim two", severity="nit", first_round=1),
        f("F3", "src/z.py", 1, "claim three", severity="nit", first_round=2),
        f("F4", "src/b.py", 7, "claim four", severity="nit", first_round=2),
    ]
    rounds = [
        make_round(1),
        make_round(2, level="medium", scope_kind="since", agents_returned=5, nit_cap=2),
    ]
    assert_golden(render_report(make_state(findings, rounds)), "nit_cap_overflow")


def test_rpt_golden_reopen() -> None:
    """FND-11/RPT-4/RPT-6: reopen section, not counted in the count line."""
    reopened = f(
        "F3",
        "src/x.py",
        5,
        "old claim",
        status="wontfix",
        reopen_round=2,
        disposition={"reason": "r", "at": "t", "snippet_hash": "h"},
    )
    state = make_state([reopened, CHARGE], two_rounds(agents_returned=9))
    assert_golden(render_report(state), "reopen")


def test_rpt_golden_rule_suggestion() -> None:
    """RPT-6/FND-16: rule suggestions follow the sections, before the Details line."""
    suggestion = (
        'Rule suggestion: "float rounding" marked wrong 3× in this repo. '
        "A REVIEW.md line such as: Do not report float rounding."
    )
    finding = f(
        "F2",
        "src/billing/tax.ts",
        12,
        "rounding uses float",
        **{"class": "float rounding"},
    )
    rounds = [
        make_round(1),
        make_round(2, scope_kind="since"),
        make_round(3, scope_kind="since", agents_returned=9, suggestions=[suggestion]),
    ]
    assert_golden(render_report(make_state([finding], rounds)), "rule_suggestion")


def test_rpt_golden_uncertain_decision_item() -> None:
    """FND-14/RPT-5: uncertain needs-decision item tagged `(uncertain)`; c1 and c2 wording."""
    c1 = f(
        "F7",
        "src/p.py",
        5,
        "rounding mode changes for refunds",
        trigger="refund of 10.005",
        evidence="p.py:5 uses ROUND_HALF_UP",
        verdict="uncertain",
        needs_decision=decision(1, before="ROUND_HALF_UP", after="ROUND_HALF_EVEN"),
    )
    c2 = f(
        "F9",
        "src/q.py",
        8,
        "second charge is sent on retry",
        trigger="gateway timeout then retry",
        evidence="q.py:8 retries without a key",
        needs_decision=decision(2, intent_quote="never charge twice"),
    )
    plain = f("F8", "src/r.py", 3, "cache may serve stale rows", verdict="uncertain")
    rounds = [make_round(1, level="xhigh", agents_returned=12)]
    assert_golden(render_report(make_state([c1, c2, plain], rounds)), "uncertain_decision")


# --- RPT-1..3 details ---------------------------------------------------------------------------


def first_line(text: str) -> str:
    return text.splitlines()[0]


def test_rpt1_model_override_and_small_diff_suffixes() -> None:
    rounds = [
        make_round(
            1,
            level="low",
            agents_returned=4,
            model_override="opus",
            small_diff={"applied": True, "finders_to": 2},
        )
    ]
    header = first_line(render_report(make_state([CHARGE], rounds)))
    assert header == (
        "review-cycle · round 1 · low · vs origin/main@abcdef1 · 4 agents"
        " · model opus · small diff: 2 finders"
    )


def test_rpt1_later_code_round_says_since_previous_head() -> None:
    rounds = [
        make_round(1, head_sha="1234567aaaa"),
        make_round(2, scope_kind="since", agents_returned=3),
    ]
    header = first_line(render_report(make_state([CHARGE], rounds)))
    assert header == "review-cycle · round 2 · high · since 1234567 · 3 agents"


def test_rpt1_header_is_vs_base_unless_the_round_scope_is_since() -> None:
    """RPT-17: later rounds with a full scope say `vs <base>@<mb7>`."""
    rounds = [make_round(1), make_round(2, scope_kind="full_base_changed")]
    header = first_line(render_report(make_state([CHARGE], rounds)))
    assert header == "review-cycle · round 2 · high · vs origin/main@abcdef1 · 9 agents"


def test_rpt3_no_stated_intent_line() -> None:
    state = make_state([CHARGE], [make_round(1, intent_none=True)])
    assert "No stated intent: the intent lens used commit messages only." in render_report(state)
    state = make_state([CHARGE], [make_round(1, intent_none=False)])
    assert "No stated intent" not in render_report(state)


def test_rpt3_nothing_to_fix_absent_when_uncertain_items_exist() -> None:
    plain = f("F8", "src/r.py", 3, "maybe", verdict="uncertain")
    state = make_state([plain], [make_round(1)])
    assert "Nothing to fix." not in render_report(state)


def test_rpt2_empty_sections_are_omitted() -> None:
    text = render_report(make_state([CHARGE], [make_round(1)]))
    for heading in ("Needs your decision", "Nit (", "Uncertain (", "Pre-existing (", "Reopen?"):
        assert heading not in text


def test_rpt4_decision_section_precedes_uncertain_and_agent_sections() -> None:
    decided = f("F1", "src/z.py", 1, "d", needs_decision=decision(1, before="a", after="b"))
    uncertain = f("F2", "src/a.py", 1, "u", verdict="uncertain")
    nit = f("F3", "src/a.py", 2, "n", severity="nit")
    pre = f("F5", "src/a.py", 3, "p", origin="pre_existing")
    text = render_report(make_state([pre, nit, uncertain, CHARGE, decided], [make_round(1)]))
    order = [
        text.index(h)
        for h in (
            "Needs your decision",
            "Agent can fix",
            "Uncertain (1)",
            "Nit (1)",
            "Pre-existing (1)",
        )
    ]
    assert order == sorted(order)


def test_rpt4_items_sorted_by_path_then_line() -> None:
    a = f("F1", "src/b.py", 1, "late path")
    b = f("F2", "src/a.py", 20, "early path late line")
    c = f("F3", "src/a.py", 3, "early path early line")
    text = render_report(make_state([a, b, c], [make_round(1)]))
    assert text.index("F3 ") < text.index("F2 ") < text.index("F1 ")


# --- RPT-8 report_findings ----------------------------------------------------------------------


def shown(chunks: list[dict]) -> list[dict]:
    return [rec for chunk in chunks for rec in chunk["findings"]]


def test_rpt8_record_fields_and_verdict_mapping() -> None:
    confirmed = f(
        "F1",
        "src/a.py",
        7,
        "claim one",
        trigger="the trigger",
        **{"class": "c" * 80},
    )
    unsure = f("F2", "src/b.py", 2, "claim two", trigger="", verdict="uncertain")
    chunks = report_findings(make_state([confirmed, unsure], [make_round(1, level="high")]))
    assert len(chunks) == 1
    assert chunks[0]["level"] == "high"
    assert chunks[0]["findings"] == [
        {
            "file": "src/a.py",
            "line": 7,
            "summary": "claim one",
            "failure_scenario": "the trigger",
            "category": "logic",
            "short_summary": "c" * 60,
            "verdict": "CONFIRMED",
        },
        {
            "file": "src/b.py",
            "line": 2,
            "summary": "claim two",
            "failure_scenario": "claim two",
            "category": "logic",
            "short_summary": "off-by-one",
            "verdict": "PLAUSIBLE",
        },
    ]
    assert "outcome" not in chunks[0]["findings"][0]


def test_rpt8_order_follows_report_sections_and_skips_unshown() -> None:
    decided = f("F1", "src/z.py", 1, "d", needs_decision=decision(1, before="a", after="b"))
    nit_shown = f("F2", "src/a.py", 1, "n1", severity="nit", first_round=2)
    nit_over = f("F3", "src/a.py", 2, "n2", severity="nit", first_round=1)
    pre = f("F5", "src/a.py", 3, "p", origin="pre_existing")
    reopened = f("F6", "src/a.py", 4, "r", status="wontfix", reopen_round=2)
    hidden = f("F7", "src/a.py", 5, "h", hidden_reason="outside_scope")
    fixed = f("F8", "src/a.py", 6, "x", status="fixed")
    state = make_state(
        [pre, nit_over, nit_shown, CHARGE, decided, reopened, hidden, fixed],
        [make_round(1), make_round(2, nit_cap=1)],
    )
    claims = [rec["summary"] for rec in shown(report_findings(state))]
    assert claims == ["d", "retry after a timeout charges twice", "n1", "p"]


def test_rpt8_chunks_of_at_most_32() -> None:
    findings = [f(f"F{i}", "src/a.py", i, f"claim {i}") for i in range(1, 41)]
    chunks = report_findings(make_state(findings, [make_round(1, level="max")]))
    assert [len(c["findings"]) for c in chunks] == [32, 8]
    assert all(c["level"] == "max" for c in chunks)
    assert [r["line"] for r in shown(chunks)] == list(range(1, 41))


def test_rpt8_exactly_32_is_one_chunk() -> None:
    findings = [f(f"F{i}", "src/a.py", i, f"claim {i}") for i in range(1, 33)]
    chunks = report_findings(make_state(findings, [make_round(1)]))
    assert [len(c["findings"]) for c in chunks] == [32]


def test_rpt8_nothing_shown_gives_no_chunks() -> None:
    assert report_findings(make_state([], [make_round(1)])) == []


# --- RPT-7 round-N.md ---------------------------------------------------------------------------


def round_md() -> str:
    nit = f("F5", "src/n.py", 1, "just a nit", severity="nit", expected="NIT-EXPECTED")
    finding = f(
        "F4",
        "src/billing/charge.ts",
        142,
        "retry after a timeout charges twice",
        evidence="charge.ts:142 retries blindly",
        expected="a retry sends the same idempotency key",
        trigger="TRIGGER-F4",
        first_round=17,
        **{"class": "retries without idempotency key"},
    )
    state = make_state([finding, nit], two_rounds(agents_returned=9, rejected=1))
    outcome = MergeOutcome(
        round_entry=state["rounds"][-1],
        votes={
            "F4": [
                verdict("N1.1", True, model="sonnet", reason="REASON-ONE"),
                verdict("N1.1", False, slot=1, model="opus", reason="REASON-TWO"),
            ]
        },
        rejected=[
            {
                "candidate": candidate("N1.2", claim="REJECTED-CLAIM"),
                "votes": [verdict("N1.2", False, reason="REJECT-REASON")],
            }
        ],
        dropped=[{"id": "N2.1", "dup_of": "N1.1"}],
        log=["finder 3 returned null"],
    )
    return render_round_md(state, outcome)


def test_rpt7_round_md_starts_with_the_report_header() -> None:
    text = round_md()
    assert "review-cycle · round 2 · high · since 04bc916 · 9 agents" in text.splitlines()[:3]


def test_rpt7_round_md_lists_findings_votes_rejected_dropped_and_log() -> None:
    text = round_md()
    assert "model | role | holds | severity | reason" in text
    for needle in (
        "REASON-ONE",
        "REASON-TWO",
        "REJECTED-CLAIM",
        "REJECT-REASON",
        "N2.1",
        "finder 3 returned null",
        "a retry sends the same idempotency key",
    ):
        assert needle in text


def test_rpt7_round_md_handoff_block_for_important_agent_can_fix() -> None:
    text = round_md()
    assert "## Hand-off for the coding flow" in text
    tail = text.split("## Hand-off for the coding flow", 1)[1]
    assert "### F4 · retries without idempotency key" in tail
    assert "Problem: retry after a timeout charges twice" in tail
    assert "Evidence: charge.ts:142 retries blindly" in tail
    assert "Expected behaviour: a retry sends the same idempotency key" in tail
    assert "Class: every instance of retries without idempotency key" in tail
    assert "F5" not in tail
    assert "NIT-EXPECTED" not in tail


# --- RPT-9 render_show --------------------------------------------------------------------------


def test_rpt9_show_has_fields_disposition_and_mark_hint() -> None:
    finding = f(
        "F3",
        "src/x.py",
        5,
        "the claim text",
        trigger="TRIGGER-TEXT",
        evidence="EVIDENCE-TEXT",
        expected="EXPECTED-TEXT",
        status="wontfix",
        disposition={
            "reason": "DISPOSITION-REASON",
            "at": "2026-10-26T12:00:00Z",
            "snippet_hash": "h",
        },
        **{"class": "CLASS-NAME"},
    )
    text = render_show(make_state([finding], [make_round(1)]), "F3")
    for needle in (
        "F3",
        "src/x.py",
        "the claim text",
        "TRIGGER-TEXT",
        "EVIDENCE-TEXT",
        "EXPECTED-TEXT",
        "CLASS-NAME",
        "wontfix",
        "DISPOSITION-REASON",
        "/review-cycle F3",
    ):
        assert needle in text


@pytest.mark.parametrize("fid", ["F1", "F2"])
def test_rpt9_show_picks_the_requested_finding(fid: str) -> None:
    one = f("F1", "src/one.py", 1, "ONE-CLAIM")
    two = f("F2", "src/two.py", 2, "TWO-CLAIM")
    text = render_show(make_state([one, two], [make_round(1)]), fid)
    mine, other = ("ONE-CLAIM", "TWO-CLAIM") if fid == "F1" else ("TWO-CLAIM", "ONE-CLAIM")
    assert mine in text
    assert other not in text


def test_rpt7_round_md_findings_block_has_st5_fields() -> None:
    text = round_md()
    for needle in ("introduced", "open", "TRIGGER-F4", "17", "charge.ts:142 retries blindly"):
        assert needle in text


def test_rpt7_handoff_excludes_decision_uncertain_and_pre_existing_items() -> None:
    plain = f("F4", "src/a.py", 1, "PLAIN-CLAIM", **{"class": "plain class"})
    decided = f(
        "F6", "src/b.py", 1, "DECISION-CLAIM", needs_decision=decision(1, before="a", after="b")
    )
    unsure = f("F7", "src/c.py", 1, "UNSURE-CLAIM", verdict="uncertain")
    pre = f("F8", "src/d.py", 1, "PRE-CLAIM", origin="pre_existing")
    state = make_state([plain, decided, unsure, pre], two_rounds(agents_returned=9))
    text = render_round_md(state, MergeOutcome(round_entry=state["rounds"][-1]))
    tail = text.split("## Hand-off for the coding flow", 1)[1]
    assert "### F4 · plain class" in tail
    for gone in ("F6", "F7", "F8", "DECISION-CLAIM", "UNSURE-CLAIM", "PRE-CLAIM"):
        assert gone not in tail


def test_rpt9_show_has_votes_verdict_and_round_numbers() -> None:
    finding = f(
        "F3",
        "src/x.py",
        5,
        "the claim text",
        severity="nit",
        verdict="uncertain",
        first_round=31,
        last_seen_round=47,
        severity_votes=[{"model": "SEVMODEL", "severity": "nit", "reason": "SEVREASON"}],
        status="intentional",
        disposition={"reason": "WHY-REASON", "at": "2026-10-26T12:00:00Z", "snippet_hash": "h"},
    )
    text = render_show(make_state([finding], [make_round(1)]), "F3")
    for needle in (
        "SEVMODEL",
        "SEVREASON",
        "uncertain",
        "31",
        "47",
        "WHY-REASON",
        "2026-10-26T12:00:00Z",
    ):
        assert needle in text


# --- code review R2 -----------------------------------------------------------------------------


def test_rpt8_short_summary_falls_back_to_claim_and_zero_line_is_omitted() -> None:
    nameless = f("F1", "src/a.py", 0, "c" * 80, **{"class": ""})
    (chunk,) = report_findings(make_state([nameless], [make_round(1)]))
    record = chunk["findings"][0]
    assert record["short_summary"] == "c" * 60
    assert "line" not in record


def test_rpt9_show_renders_every_st5_field() -> None:
    finding = f(
        "F3",
        "src/x.py",
        5,
        "claim",
        fingerprint="FINGERPRINT-X",
        anchor_file_id="FILEID-X",
        response_type="RESPONSE-X",
        reopen_round=7,
        moved_from_decision=True,
        hidden_reason="outside_scope",
        snippet="SNIPPET-X",
        needs_decision=decision(
            3,
            before="BEFORE-X",
            after="AFTER-X",
            intent_quote="QUOTE-X",
            options=[{"label": "LABEL-X", "observable": "OBS-X"}],
        ),
    )
    state = make_state([finding], [make_round(1)])
    outcome = MergeOutcome(round_entry=state["rounds"][-1])
    for text in (render_show(state, "F3"), render_round_md(state, outcome)):
        for needle in (
            "FINGERPRINT-X",
            "FILEID-X",
            "RESPONSE-X",
            "7",
            "yes",
            "outside_scope",
            "SNIPPET-X",
            "BEFORE-X",
            "AFTER-X",
            "QUOTE-X",
            "LABEL-X",
            "OBS-X",
        ):
            assert needle in text


def test_rpt17_show_and_round_md_render_null_and_booleans_plainly() -> None:
    finding = f("F3", "src/x.py", 5, "claim", trigger="", moved_from_decision=True, symbol=None)
    state = make_state([finding], [make_round(1)])
    outcome = MergeOutcome(round_entry=state["rounds"][-1])
    for text in (render_show(state, "F3"), render_round_md(state, outcome)):
        assert "(symbol: -)" in text and "trigger: -" in text
        assert "moved_from_decision: yes" in text and "hidden_reason: -" in text
        assert not any(line != line.rstrip() for line in text.splitlines())
        assert "None" not in text and "True" not in text and "False" not in text


def test_rpt17_show_hint_offers_fix_only_for_a_decision() -> None:
    decided = f("F3", "src/x.py", 5, "claim", needs_decision=decision(3))
    hint = render_show(make_state([decided], [make_round(1)]), "F3").splitlines()[-1]
    for verb in ("intentional|wontfix|wrong|superseded", "F3 open", "F3 fix"):
        assert verb in hint
    plain = render_show(make_state([CHARGE], [make_round(1)]), "F4").splitlines()[-1]
    assert " fix" not in plain and "F4 open" in plain
