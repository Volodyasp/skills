"""Tests for `checksum` (SPECS WF-13, Python side; ST-11 result shape)."""

from __future__ import annotations

import copy

import pytest
from helpers_pure import candidate, nd, verdict
from review_cycle.checksum import checksum_text, fnv1a32, result_checksum

US, RS, GS, FS = "\x1f", "\x1e", "\x1d", "\x1c"


def rec(*fields: str) -> str:
    return US.join(fields) + RS


# Reference values: FNV-1a 32-bit over Unicode code points (not UTF-8 bytes).
FNV_VECTORS = [
    ("", "811c9dc5"),
    ("a", "e40c292c"),
    ("foobar", "bf9cf968"),
    ("привет", "9015dafb"),
    ("\U0001f600", "0650a71f"),
    ("\ud800", "0481d51f"),
    ("a\U0001f600б", "9d6a1a2f"),
    ("x\ud800y", "554310b4"),
]


@pytest.mark.parametrize(("text", "expected"), FNV_VECTORS)
def test_wf13_fnv1a32_vectors(text: str, expected: str) -> None:
    """WF-13: ASCII, Cyrillic, emoji, lone surrogate and empty vectors."""
    assert fnv1a32(text) == expected


def test_wf13_fnv_is_8_lowercase_hex() -> None:
    """WF-13: hex 8 lower-case, zero-padded."""
    out = fnv1a32("anything")
    assert len(out) == 8
    assert out == out.lower()
    int(out, 16)


def _result() -> dict:
    c1 = candidate("N1.1", snippet="a\nb", claim="клейм 😀")
    c2 = candidate("S1", of_class="off-by-one", finder=0, line=0, lens="")
    del c2["broken_by"]
    v1 = verdict(
        "N1.1",
        True,
        slot=1,
        batch=2,
        needs_decision=nd(
            2,
            before="b",
            after="a",
            intent_quote="q",
            options=[
                {"label": "A", "observable": "x"},
                {"label": "B", "observable": "y"},
            ],
        ),
    )
    v2 = verdict("F1", False, kind="recheck", role="tiebreak", prevented_by="guard")
    del v2["needs_decision"]
    return {
        "candidates": [c1, c2],
        "verdicts": [v1, v2],
        "dropped": [{"id": "N2.1", "dup_of": "N1.1"}],
        "missing": [{"item_id": "N1.1", "role": "vote", "slot": 0}],
    }


def _expected_text() -> str:
    c1 = rec(
        "C", "N1.1", "logic", "off-by-one", "src/a.py", "10", "f", "a\nb", "клейм 😀",
        "call f with an empty list", "a.py:10 sets x = 1", "x starts at 0", "bugs", "1",
        "", "0", "", "",
    )  # fmt: skip
    c2 = rec(
        "C", "S1", "logic", "off-by-one", "src/a.py", "0", "f", "x = 1",
        "x starts at the wrong value", "call f with an empty list", "a.py:10 sets x = 1",
        "x starts at 0", "", "0", "", "", "", "off-by-one",
    )  # fmt: skip
    v1 = rec(
        "V", "N1.1", "new", "vote", "1", "sonnet", "2", "1", "important", "reason",
        "evidence", "trigger", "", "2", "b", "a", "q", "A" + GS + "x" + FS + "B" + GS + "y",
    )  # fmt: skip
    v2 = rec(
        "V", "F1", "recheck", "tiebreak", "0", "sonnet", "0", "0", "", "reason",
        "evidence", "trigger", "guard", "", "", "", "", "",
    )  # fmt: skip
    return c1 + c2 + v1 + v2 + rec("D", "N2.1", "N1.1") + rec("M", "N1.1", "vote", "0")


def test_wf13_checksum_text_exact_records_in_order() -> None:
    """WF-13: C, V, D, M records; null/missing -> empty; ints as digits; bool as 1/0; options join."""
    assert checksum_text(_result()) == _expected_text()


def test_wf13_record_kinds_are_ordered_c_then_v_then_d_then_m() -> None:
    """WF-13: all candidates, then all verdicts, then dropped, then missing."""
    text = checksum_text(_result())
    tags = [r.split(US)[0] for r in text.split(RS) if r]
    assert tags == ["C", "C", "V", "V", "D", "M"]


def test_wf13_empty_result_has_empty_text() -> None:
    """WF-13: no records -> empty text -> checksum of the empty string."""
    empty: dict = {"candidates": [], "verdicts": [], "dropped": [], "missing": []}
    assert checksum_text(empty) == ""
    assert result_checksum(empty) == "811c9dc5"


def test_wf13_result_checksum_is_fnv_of_text() -> None:
    """WF-13: result_checksum == fnv1a32(checksum_text)."""
    r = _result()
    assert result_checksum(r) == fnv1a32(checksum_text(r))


def test_wf13_result_checksum_known_value() -> None:
    """WF-13: fixed value for the reference result (guards JS parity drift)."""
    assert result_checksum(_result()) == EXPECTED_CHECKSUM


# fnv1a32 of _expected_text(), computed with an independent reference implementation.
EXPECTED_CHECKSUM = "df23d316"


def test_wf13_checksum_ignores_other_fields() -> None:
    """WF-13: only the four record kinds enter the checksum (log, stats, checksum do not)."""
    base = _result()
    other = copy.deepcopy(base)
    other.update({"log": ["x"], "stats": {"agents_started": 1}, "checksum": "ffffffff"})
    assert result_checksum(base) == result_checksum(other)


def test_wf13_checksum_detects_one_char_change() -> None:
    """WF-13: a one-character change in a record changes the checksum."""
    base = _result()
    changed = copy.deepcopy(base)
    changed["candidates"][0]["claim"] += "."
    assert result_checksum(base) != result_checksum(changed)


@pytest.mark.parametrize("text", ["plain", "привет", "\U0001f600", "x\ud800y", ""])
def test_wf13_checksum_text_passes_special_strings_through(text: str) -> None:
    """WF-13: Cyrillic, emoji and lone surrogates enter the text unescaped."""
    r = {
        "candidates": [candidate("N1.1", claim=text)],
        "verdicts": [],
        "dropped": [],
        "missing": [],
    }
    assert text in checksum_text(r)
    assert result_checksum(r) == fnv1a32(checksum_text(r))


def test_wf13_explicit_none_fields_serialise_as_empty_strings() -> None:
    """WF-13: null/undefined -> empty; an empty options list -> empty string."""
    c = candidate("N1.1", trigger=None, finder=None, of_class=None, broken_by=None)
    v = verdict("N1.1", True, prevented_by=None, needs_decision=nd(0, options=[]))
    result = {"candidates": [c], "verdicts": [v], "dropped": [], "missing": []}
    expected = rec(
        "C", "N1.1", "logic", "off-by-one", "src/a.py", "10", "f", "x = 1",
        "x starts at the wrong value", "", "a.py:10 sets x = 1", "x starts at 0", "bugs", "",
        "", "", "", "",
    ) + rec(
        "V", "N1.1", "new", "vote", "0", "sonnet", "0", "1", "important", "reason",
        "evidence", "trigger", "", "0", "", "", "", "",
    )  # fmt: skip
    assert checksum_text(result) == expected
