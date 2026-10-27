"""Review levels: finder lenses, verifier models and keep rules per level (FND-1..3)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

# Start values chosen as round numbers with no data; tune from HANDOFF §11 runs.
SMALL_DIFF_MAX_LINES = 50
SMALL_DIFF_MAX_FILES = 3
SMALL_DIFF_FINDERS = 2
RULE_SUGGESTION_REPEATS = 3
FUZZY_SNIPPET_MIN = 0.80
FUZZY_TEXT_MIN = 0.50
NIT_CAP_DEFAULT = 5
EXPECTED_CANDIDATES = 15
VERIFY_BATCH_MAX = 8

FINDER_MODEL = "sonnet"


@dataclass(frozen=True)
class Finder:
    """One finder agent: a lens id and the file order it walks."""

    lens: str
    order: Literal["forward", "reverse"] = "forward"


@dataclass(frozen=True)
class Level:
    """Agent configuration of one level.

    `votes` lists the verifier model per vote slot; `tiebreak` and `sweep` are model names
    or None when the level has none.
    """

    name: str
    code_finders: tuple[Finder, ...]
    doc_finders: tuple[Finder, ...]
    votes: tuple[str, ...]
    keep_rule: str
    tiebreak: str | None
    depth: str
    sweep: str | None


_DEPTH_LOW = "anchor and its file"
_DEPTH_MEDIUM = _DEPTH_LOW + " + callers and callees"
_DEPTH_HIGH = _DEPTH_MEDIUM + " + tests and config"
_DEPTH_XHIGH = "name a concrete trigger or the line that prevents it"

_CODE_LOW = (Finder("bugs"), Finder("intent"))
_CODE_MEDIUM = (*_CODE_LOW, Finder("rules"))
_CODE_HIGH = (*_CODE_MEDIUM, Finder("history"))
_CODE_XHIGH = (*_CODE_HIGH, Finder("bugs", "reverse"))
_CODE_MAX = (*_CODE_XHIGH, Finder("system-fit"))

_DOC_LOW = (Finder("contradictions-gaps"), Finder("code-claims"))
_DOC_MEDIUM = (*_DOC_LOW, Finder("ambiguity"))
_DOC_HIGH = (*_DOC_MEDIUM, Finder("unneeded"))
_DOC_XHIGH = (*_DOC_HIGH, Finder("contradictions-gaps", "reverse"))
_DOC_MAX = (*_DOC_XHIGH, Finder("consistency-links"))

LEVELS: dict[str, Level] = {
    "low": Level("low", _CODE_LOW, _DOC_LOW, ("sonnet", "sonnet"), "all2", None, _DEPTH_LOW, None),
    "medium": Level(
        "medium", _CODE_MEDIUM, _DOC_MEDIUM, ("sonnet", "sonnet"), "all2", None, _DEPTH_MEDIUM, None
    ),
    "high": Level(
        "high",
        _CODE_HIGH,
        _DOC_HIGH,
        ("sonnet", "opus"),
        "all2_tiebreak",
        "opus",
        _DEPTH_HIGH,
        None,
    ),
    "xhigh": Level(
        "xhigh",
        _CODE_XHIGH,
        _DOC_XHIGH,
        ("sonnet", "sonnet", "opus"),
        "maj3",
        None,
        _DEPTH_XHIGH,
        None,
    ),
    "max": Level(
        "max",
        _CODE_MAX,
        _DOC_MAX,
        ("opus", "opus", "opus"),
        "maj3",
        None,
        _DEPTH_XHIGH,
        "sonnet",
    ),
}


def _assert_no_haiku() -> None:
    for level in LEVELS.values():
        if any("haiku" in m for m in (*level.votes, level.tiebreak or "")):
            raise AssertionError(f"level {level.name}: haiku verifier models are not allowed")


_assert_no_haiku()


def level_config(level: str, mode: str, model_override: str | None, small: bool) -> dict:
    """Build the plan's `level_config` (ST-1) for a level.

    Args:
        level: key of `LEVELS`.
        mode: "code" or "document"; selects the finder list.
        model_override: replaces every role model (finders, votes, tiebreak, sweep) when set.
        small: apply the small-diff rule and keep only the first `SMALL_DIFF_FINDERS` finders.

    Returns:
        Dict with keys finders[{lens, order}], finder_model, votes, tiebreak, keep_rule,
        depth, sweep.

    Raises:
        AssertionError: no override is given and a verifier/tie-break model matches "haiku".
    """
    spec = LEVELS[level]
    finders = spec.code_finders if mode == "code" else spec.doc_finders
    if small:
        finders = finders[:SMALL_DIFF_FINDERS]
    if model_override is None:
        if any("haiku" in m for m in (*spec.votes, spec.tiebreak or "")):
            raise AssertionError(f"level {level}: haiku verifier models need --model")
        finder_model = FINDER_MODEL
        votes = list(spec.votes)
        tiebreak = spec.tiebreak
        sweep = spec.sweep
    else:
        finder_model = model_override
        votes = [model_override] * len(spec.votes)
        tiebreak = model_override if spec.tiebreak else None
        sweep = model_override if spec.sweep else None
    return {
        "finders": [{"lens": f.lens, "order": f.order} for f in finders],
        "finder_model": finder_model,
        "votes": votes,
        "tiebreak": tiebreak,
        "keep_rule": spec.keep_rule,
        "depth": spec.depth,
        "sweep": sweep,
    }
