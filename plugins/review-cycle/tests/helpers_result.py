"""Builders for fake workflow results (ST-11) used by the S02b tests.

The checksum is computed with the Python implementation (`checksum.result_checksum`), so these
helpers raise `NotImplementedError` until the checksum module exists.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

PROVENANCE = "review-cycle/workflows/review.js"
DEFAULT_CLASS = "unchecked call"
SEEDED = "    return risky(x)  # seeded"

Slots = Sequence[bool | None]


def cand(
    *,
    path: str = "src/app.py",
    line: int = 21,
    symbol: str = "handler",
    snippet: str = SEEDED,
    claim: str = "risky(x) raises on an empty x",
    category: str = "logic",
    cls: str = DEFAULT_CLASS,
    trigger: str = "x is empty",
    evidence: str = "src/app.py:21 calls risky without a guard",
    expected: str = "empty x is handled",
    scope_note: str = "",
    broken_by_path: str = "",
    broken_by_line: int = 0,
) -> dict[str, Any]:
    """Return a finder item (ST-9) without the ids the workflow adds."""
    return {
        "category": category,
        "class": cls,
        "path": path,
        "line": line,
        "symbol": symbol,
        "snippet": snippet,
        "claim": claim,
        "trigger": trigger,
        "evidence": evidence,
        "expected": expected,
        "broken_by": {"path": broken_by_path, "line": broken_by_line},
        "scope_note": scope_note,
    }


def _verdict(
    item_id: str,
    kind: str,
    role: str,
    slot: int,
    model: str,
    holds: bool,
    severity: str,
    decision: Mapping[str, Any] | None,
) -> dict[str, Any]:
    return {
        "item_id": item_id,
        "kind": kind,
        "role": role,
        "slot": slot,
        "model": model,
        "batch": 0,
        "holds": holds,
        "severity": severity if holds else "",
        "reason": f"reason of {role} {slot}",
        "evidence": "verifier evidence",
        "trigger": "verifier trigger",
        "prevented_by": "",
        "needs_decision": dict(decision)
        if decision
        else {"criterion": 0, "before": "", "after": "", "intent_quote": "", "options": []},
    }


def build_result(
    plan: Mapping[str, Any],
    candidates: Sequence[Mapping[str, Any]] = (),
    votes: Mapping[str, Slots] | None = None,
    tiebreaks: Mapping[str, bool | None] | None = None,
    recheck: Mapping[str, Slots] | None = None,
    *,
    severity: str | Mapping[str, str] = "important",
    decisions: Mapping[str, Mapping[str, Any]] | None = None,
    dropped: Sequence[Mapping[str, str]] = (),
) -> dict[str, Any]:
    """Build a started, fully covered workflow result for `plan`.

    Args:
        plan: parsed `plan.json`.
        candidates: finder items from `cand()`; they get ids `N1.1`, `N1.2`, ...
        votes: per candidate id, one entry per vote slot (True holds, False refutes, None =
            missing); default: every slot holds.
        tiebreaks: per item id, the tie-break verdict (None = missing); default: refutes.
            Tie-break rows are generated only where the plan's level has a tie-break and the
            votes are split (ST-12 coverage rule).
        recheck: like `votes` for the plan's re-check items.
        severity: severity of holding verdicts, or per item id.
        decisions: per item id, the `needs_decision` object of that item's holding verdicts.
        dropped: `dropped[]` records.
    """
    args = plan["workflow"]["args"]
    models: list[str] = list(args["votes"])
    tiebreak_model = args.get("tiebreak")
    lens = _lens(args["finders"][0]) if args["finders"] else "bugs"
    items = [
        {**dict(c), "id": f"N1.{k}", "lens": lens, "finder": 1, "of_class": ""}
        for k, c in enumerate(candidates, 1)
    ]
    todo = [(c["id"], "new", votes) for c in items]
    todo += [(r["id"], "recheck", recheck) for r in plan.get("recheck", [])]
    verdicts: list[dict[str, Any]] = []
    missing: list[dict[str, Any]] = []
    for item_id, kind, table in todo:
        slots = list(table[item_id]) if table and item_id in table else [True] * len(models)
        sev = severity if isinstance(severity, str) else severity.get(item_id, "important")
        nd = (decisions or {}).get(item_id)
        for slot, holds in enumerate(slots):
            if holds is None:
                missing.append({"item_id": item_id, "role": "vote", "slot": slot})
            else:
                verdicts.append(_verdict(item_id, kind, "vote", slot, models[slot], holds, sev, nd))
        split = any(h is True for h in slots) and not all(h is True for h in slots)
        if tiebreak_model and split:
            tb = (tiebreaks or {}).get(item_id, False)
            if tb is None:
                missing.append({"item_id": item_id, "role": "tiebreak", "slot": 0})
            else:
                verdicts.append(_verdict(item_id, kind, "tiebreak", 0, tiebreak_model, tb, sev, nd))
    result: dict[str, Any] = {
        "provenance": PROVENANCE,
        "v": 1,
        "started": True,
        "plan_id": plan["plan_id"],
        "echo": {
            "level": args["level"],
            "mode": args["mode"],
            "finders": args["finders"],
            "votes": args["votes"],
            "tiebreak": args.get("tiebreak"),
            "recheck_ids": [r["id"] for r in plan.get("recheck", [])],
        },
        "candidates": items,
        "dropped": [dict(d) for d in dropped],
        "verdicts": verdicts,
        "missing": missing,
        "stats": {
            "agents_started": len(args["finders"]) + len(verdicts),
            "agents_returned": len(args["finders"]) + len(verdicts),
            "finders_null": 0,
            "verifiers_null": len(missing),
        },
        "log": [],
    }
    from review_cycle.checksum import result_checksum

    result["checksum"] = result_checksum(result)
    return result


def _lens(finder: object) -> str:
    return str(finder["lens"]) if isinstance(finder, dict) else str(finder)


def runtime_wrapped(result: Mapping[str, Any]) -> dict[str, Any]:
    """Return the runtime output-file shape: the result under a `result` key (CLI-12)."""
    return {"result": dict(result)}


def with_bad_checksum(result: Mapping[str, Any]) -> dict[str, Any]:
    """Return a copy whose checksum differs in one character."""
    broken = dict(result)
    last = broken["checksum"][-1]
    broken["checksum"] = broken["checksum"][:-1] + ("0" if last != "0" else "1")
    return broken


def without_first_verdict(result: Mapping[str, Any]) -> dict[str, Any]:
    """Return a copy missing one verdict row and no `missing` entry for it (coverage gap).

    The checksum is recomputed so that coverage, not the checksum, is the failing check.
    """
    from review_cycle.checksum import result_checksum

    broken = dict(result)
    broken["verdicts"] = list(result["verdicts"])[1:]
    broken["checksum"] = result_checksum(broken)
    return broken
