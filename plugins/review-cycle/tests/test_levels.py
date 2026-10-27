"""Tests for `levels` (SPECS FND-1, FND-2, FND-3)."""

from __future__ import annotations

import pytest
from review_cycle import levels
from review_cycle.levels import LEVELS, Finder, Level, level_config

CODE_LENSES = {
    "low": ["bugs", "intent"],
    "medium": ["bugs", "intent", "rules"],
    "high": ["bugs", "intent", "rules", "history"],
    "xhigh": ["bugs", "intent", "rules", "history", "bugs"],
    "max": ["bugs", "intent", "rules", "history", "bugs", "system-fit"],
}
DOC_LENSES = {
    "low": ["contradictions-gaps", "code-claims"],
    "medium": ["contradictions-gaps", "code-claims", "ambiguity"],
    "high": ["contradictions-gaps", "code-claims", "ambiguity", "unneeded"],
    "xhigh": ["contradictions-gaps", "code-claims", "ambiguity", "unneeded", "contradictions-gaps"],
    "max": [
        "contradictions-gaps",
        "code-claims",
        "ambiguity",
        "unneeded",
        "contradictions-gaps",
        "consistency-links",
    ],
}
# level -> (votes, keep_rule, tiebreak, sweep)
ROLES = {
    "low": (("sonnet", "sonnet"), "all2", None, None),
    "medium": (("sonnet", "sonnet"), "all2", None, None),
    "high": (("sonnet", "opus"), "all2_tiebreak", "opus", None),
    "xhigh": (("sonnet", "sonnet", "opus"), "maj3", None, None),
    "max": (("opus", "opus", "opus"), "maj3", None, "sonnet"),
}


def test_fnd1_levels_are_the_five_named_levels() -> None:
    """FND-1: LEVELS has exactly low..max."""
    assert list(LEVELS) == ["low", "medium", "high", "xhigh", "max"]


@pytest.mark.parametrize("name", list(CODE_LENSES))
def test_fnd1_code_finders(name: str) -> None:
    """FND-1: code finder lenses per level; the reverse finder is `bugs/reverse`."""
    lenses = [f.lens for f in LEVELS[name].code_finders]
    assert lenses == CODE_LENSES[name]


@pytest.mark.parametrize("name", list(DOC_LENSES))
def test_fnd1_doc_finders(name: str) -> None:
    """FND-1: document finder lenses per level."""
    assert [f.lens for f in LEVELS[name].doc_finders] == DOC_LENSES[name]


@pytest.mark.parametrize("name", ["xhigh", "max"])
def test_fnd1_reverse_finder_is_the_fifth_one(name: str) -> None:
    """FND-1: `+ bugs/reverse` and `+ contradictions-gaps/reverse` walk in reverse order."""
    assert LEVELS[name].code_finders[4] == Finder("bugs", "reverse")
    assert LEVELS[name].doc_finders[4] == Finder("contradictions-gaps", "reverse")
    forward = [f for f in LEVELS[name].code_finders if f.order == "forward"]
    assert len(forward) == len(LEVELS[name].code_finders) - 1


@pytest.mark.parametrize("name", list(ROLES))
def test_fnd1_votes_keep_rule_tiebreak_sweep(name: str) -> None:
    """FND-1: verifier models, keep rule, tie-break and sweep per level."""
    votes, rule, tiebreak, sweep = ROLES[name]
    level = LEVELS[name]
    assert level.votes == votes
    assert level.keep_rule == rule
    assert level.tiebreak == tiebreak
    assert level.sweep == sweep


def test_fnd1_depth_per_level() -> None:
    """FND-1: depth grows low < medium < high; xhigh and max name a concrete trigger."""
    assert LEVELS["low"].depth == "anchor and its file"
    assert LEVELS["medium"].depth == "anchor and its file + callers and callees"
    assert LEVELS["high"].depth == "anchor and its file + callers and callees + tests and config"
    expected = "name a concrete trigger or the line that prevents it"
    assert LEVELS["xhigh"].depth == expected
    assert LEVELS["max"].depth == expected


def test_fnd2_no_level_uses_haiku() -> None:
    """FND-2: no verifier/tie-break model matches haiku (also asserted at import)."""
    for level in LEVELS.values():
        assert not any("haiku" in m for m in (*level.votes, level.tiebreak or ""))


def test_fnd3_constants() -> None:
    """FND-3: start values."""
    assert levels.SMALL_DIFF_MAX_LINES == 50
    assert levels.SMALL_DIFF_MAX_FILES == 3
    assert levels.SMALL_DIFF_FINDERS == 2
    assert levels.RULE_SUGGESTION_REPEATS == 3
    assert levels.FUZZY_SNIPPET_MIN == 0.80
    assert levels.FUZZY_TEXT_MIN == 0.50
    assert levels.NIT_CAP_DEFAULT == 5
    assert levels.EXPECTED_CANDIDATES == 15
    assert levels.VERIFY_BATCH_MAX == 8


def test_fnd1_finder_model_is_sonnet() -> None:
    """FND-1: finder model is sonnet at every level."""
    assert levels.FINDER_MODEL == "sonnet"


@pytest.mark.parametrize("name", list(ROLES))
def test_level_config_code(name: str) -> None:
    """FND-1/ST-1: level_config mirrors the level table for code mode."""
    votes, rule, tiebreak, sweep = ROLES[name]
    cfg = level_config(name, "code", None, False)
    assert [f["lens"] for f in cfg["finders"]] == CODE_LENSES[name]
    assert cfg["finder_model"] == "sonnet"
    assert list(cfg["votes"]) == list(votes)
    assert cfg["keep_rule"] == rule
    assert cfg["tiebreak"] == tiebreak
    assert cfg["sweep"] == sweep
    assert cfg["depth"] == LEVELS[name].depth


def test_level_config_document_uses_doc_finders() -> None:
    """FND-1: document mode takes the doc finder list, orders preserved."""
    cfg = level_config("xhigh", "document", None, False)
    assert [(f["lens"], f["order"]) for f in cfg["finders"]] == [
        ("contradictions-gaps", "forward"),
        ("code-claims", "forward"),
        ("ambiguity", "forward"),
        ("unneeded", "forward"),
        ("contradictions-gaps", "reverse"),
    ]


@pytest.mark.parametrize("mode", ["code", "document"])
def test_level_config_small_keeps_first_two_finders(mode: str) -> None:
    """RND-13/FND-3: small diff keeps the first SMALL_DIFF_FINDERS finders."""
    full = level_config("max", mode, None, False)["finders"]
    small = level_config("max", mode, None, True)["finders"]
    assert small == full[:2]


def test_fnd2_model_override_replaces_every_role() -> None:
    """FND-2: --model X replaces finder, vote, tie-break and sweep models."""
    cfg = level_config("high", "code", "opus", False)
    assert cfg["finder_model"] == "opus"
    assert list(cfg["votes"]) == ["opus", "opus"]
    assert cfg["tiebreak"] == "opus"
    cfg = level_config("max", "code", "sonnet", False)
    assert list(cfg["votes"]) == ["sonnet"] * 3
    assert cfg["sweep"] == "sonnet"


def test_fnd2_override_keeps_absent_roles_absent() -> None:
    """FND-2: a level without tie-break/sweep stays without them under an override."""
    cfg = level_config("low", "code", "opus", False)
    assert cfg["tiebreak"] is None
    assert cfg["sweep"] is None
    assert list(cfg["votes"]) == ["opus", "opus"]


def _haiku_level(monkeypatch: pytest.MonkeyPatch) -> None:
    bad = Level(
        "bad",
        (Finder("bugs"),),
        (Finder("ambiguity"),),
        ("haiku", "sonnet"),
        "all2",
        None,
        "d",
        None,
    )
    monkeypatch.setitem(LEVELS, "bad", bad)


def test_fnd2_haiku_without_override_asserts(monkeypatch: pytest.MonkeyPatch) -> None:
    """FND-2: level_config asserts when a verifier model matches haiku and no override is set."""
    _haiku_level(monkeypatch)
    with pytest.raises(AssertionError):
        level_config("bad", "code", None, False)


def test_fnd2_haiku_with_override_is_allowed(monkeypatch: pytest.MonkeyPatch) -> None:
    """FND-2: the haiku assertion applies only without an override."""
    _haiku_level(monkeypatch)
    cfg = level_config("bad", "code", "opus", False)
    assert list(cfg["votes"]) == ["opus", "opus"]


def test_fnd2_override_haiku_is_allowed_for_every_role() -> None:
    """FND-2: with an override, haiku is accepted (the assertion applies only without one)."""
    cfg = level_config("high", "code", "haiku", False)
    assert cfg["finder_model"] == "haiku"
    assert list(cfg["votes"]) == ["haiku", "haiku"]
    assert cfg["tiebreak"] == "haiku"
