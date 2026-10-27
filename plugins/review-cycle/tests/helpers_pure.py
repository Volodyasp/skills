"""Literal builders for the pure-module tests (no git, no subprocess).

Shapes follow SPECS ST-1, ST-4..ST-6, ST-9..ST-11. Builders return fresh dicts so tests can
mutate them freely.
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterable, Sequence
from typing import Any

from review_cycle.checksum import result_checksum


def sha(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def candidate(cid: str, **kw: Any) -> dict:
    """ST-11 candidate. Defaults describe a code finding in `src/a.py`."""
    base: dict[str, Any] = {
        "id": cid,
        "category": "logic",
        "class": "off-by-one",
        "path": "src/a.py",
        "line": 10,
        "symbol": "f",
        "snippet": "x = 1",
        "claim": "x starts at the wrong value",
        "trigger": "call f with an empty list",
        "evidence": "a.py:10 sets x = 1",
        "expected": "x starts at 0",
        "lens": "bugs",
        "finder": 1,
        "of_class": "",
        "broken_by": {"path": "", "line": 0},
        "scope_note": "",
    }
    base.update(kw)
    return base


def nd(criterion: int = 0, **kw: Any) -> dict:
    """ST-10 `needs_decision` object; criterion 0 = no flag."""
    base: dict[str, Any] = {
        "criterion": criterion,
        "before": "",
        "after": "",
        "intent_quote": "",
        "options": [],
    }
    base.update(kw)
    return base


def verdict(item_id: str, holds: bool, **kw: Any) -> dict:
    """ST-11 verdict row. `severity` defaults to important when it holds, else empty."""
    base: dict[str, Any] = {
        "item_id": item_id,
        "kind": "new",
        "role": "vote",
        "slot": 0,
        "model": "sonnet",
        "batch": 0,
        "holds": holds,
        "severity": "important" if holds else "",
        "reason": "reason",
        "evidence": "evidence",
        "trigger": "trigger",
        "prevented_by": "",
        "needs_decision": nd(),
    }
    base.update(kw)
    return base


def make_plan(
    *,
    round_n: int = 1,
    mode: str = "code",
    level: str = "low",
    votes: Sequence[str] = ("sonnet", "sonnet"),
    tiebreak: str | None = None,
    keep_rule: str = "all2",
    scope_files: Sequence[str] = ("src/a.py",),
    sections: Sequence[str] = (),
    recheck_ids: Sequence[str] = (),
    plan_id: str = "plan-1",
    status: str = "ready",
    file_ids: dict[str, str] | None = None,
    scope_kind: str | None = None,
) -> dict:
    """ST-1 plan with only the fields `result.validate` and `merge_round` read.

    `scope_kind` defaults to the pre-RPT-18 shape (`full` for round <= 2, `since` after) but can
    be set independently of `round_n`, since a round's scope kind and its number are no longer
    tied together (FND-12, DOC-5 key on `scope.kind`, not the round number).
    """
    finders = [{"lens": "bugs", "order": "forward"}, {"lens": "intent", "order": "forward"}]
    recheck = [{"id": rid, "path": "src/a.py"} for rid in recheck_ids]
    kind = scope_kind if scope_kind is not None else ("full" if round_n <= 2 else "since")
    return {
        "v": 1,
        "plan_id": plan_id,
        "created_at": "2026-10-26T10:00:00Z",
        "status": status,
        "mode": mode,
        "round": round_n,
        "level": level,
        "branch": "feature/x",
        "base_ref": "origin/main",
        "merge_base": "a" * 40,
        "head_sha": "b" * 40,
        "tree_sha": "c" * 40,
        "change_id": "chg-" + str(round_n),
        "file_ids": dict(file_ids or {}),
        "model_override": None,
        "level_config": {
            "finders": finders,
            "finder_model": "sonnet",
            "votes": list(votes),
            "tiebreak": tiebreak,
            "keep_rule": keep_rule,
            "depth": "anchor and its file",
            "sweep": None,
        },
        "small_diff": {"applied": False},
        "scope": {
            "kind": kind,
            "files": list(scope_files),
            "deleted": [],
            "sections": list(sections),
            "lines": 5,
        },
        "recheck": recheck,
        "intent": {"none": False, "sources": []},
        "review_md": {"path": None, "nit_cap": 5},
        "workflow": {
            "name": "review-cycle:round",
            "args": {
                "v": 1,
                "plan_id": plan_id,
                "mode": mode,
                "level": level,
                "finders": finders,
                "votes": list(votes),
                "tiebreak": tiebreak,
                "recheck": recheck,
            },
        },
    }


def make_result(
    plan: dict,
    candidates: Iterable[dict] = (),
    verdicts: Iterable[dict] = (),
    *,
    missing: Iterable[dict] = (),
    dropped: Iterable[dict] = (),
    stats: dict | None = None,
    log: Iterable[str] = (),
    checksum: bool = True,
) -> dict:
    """ST-11 result echoing `plan`. With `checksum`, the checksum is the real one (WF-13)."""
    args = plan["workflow"]["args"]
    result: dict[str, Any] = {
        "provenance": "review-cycle/workflows/review.js",
        "v": 1,
        "started": True,
        "plan_id": plan["plan_id"],
        "echo": {
            "level": args["level"],
            "mode": args["mode"],
            "finders": args["finders"],
            "votes": args["votes"],
            "tiebreak": args["tiebreak"],
            "recheck_ids": [r["id"] for r in args["recheck"]],
        },
        "candidates": list(candidates),
        "dropped": list(dropped),
        "verdicts": list(verdicts),
        "missing": list(missing),
        "stats": stats
        or {"agents_started": 6, "agents_returned": 6, "finders_null": 0, "verifiers_null": 0},
        "log": list(log),
        "checksum": "00000000",
    }
    if checksum:
        result["checksum"] = result_checksum(result)
    return result


def full_votes(item_id: str, holds: Sequence[bool | None], **kw: Any) -> list[dict]:
    """Vote rows for slots 0..n-1; `None` entries are omitted (use `missing_rows` for them)."""
    return [verdict(item_id, h, slot=slot, **kw) for slot, h in enumerate(holds) if h is not None]


def missing_rows(item_id: str, holds: Sequence[bool | None], role: str = "vote") -> list[dict]:
    return [
        {"item_id": item_id, "role": role, "slot": slot}
        for slot, h in enumerate(holds)
        if h is None
    ]


def make_finding(fid: str = "F1", **kw: Any) -> dict:
    """ST-5 finding. Top-level keys in `kw` override; `path`/`line`/`symbol`/`snippet` set the anchor."""
    anchor = {
        "path": kw.pop("path", "src/a.py"),
        "line": kw.pop("line", 10),
        "symbol": kw.pop("symbol", "f"),
        "snippet": kw.pop("snippet", "x = 1"),
    }
    base: dict[str, Any] = {
        "id": fid,
        "fingerprint": "fp-" + fid,
        "category": "logic",
        "class": "off-by-one",
        "severity": "important",
        "severity_votes": [{"model": "sonnet", "severity": "important", "reason": "r"}],
        "verdict": "confirmed",
        "origin": "introduced",
        "anchor": anchor,
        "anchor_file_id": "fid-a",
        "claim": "x starts at the wrong value",
        "evidence": "a.py:10 sets x = 1",
        "trigger": "call f with an empty list",
        "expected": "x starts at 0",
        "status": "open",
        "disposition": None,
        "needs_decision": None,
        "first_round": 1,
        "last_seen_round": 1,
        "response_type": None,
        "reopen_round": None,
        "moved_from_decision": False,
        "hidden_reason": None,
    }
    base.update(kw)
    return base


def make_round(n: int = 1, **kw: Any) -> dict:
    """ST-6 round entry with neutral values."""
    base: dict[str, Any] = {
        "n": n,
        "level": "high",
        "model_override": None,
        "plan_id": f"plan-{n}",
        "created_at": "2026-10-26T10:00:00Z",
        "merged_at": "2026-10-26T10:05:00Z",
        "base_sha": "abcdef1234567890",
        "head_sha": "04bc9160000000000",
        "tree_sha": "t" * 40,
        "change_id": f"chg-{n}",
        "scope_kind": "full",
        "files_in_scope": 2,
        "lines_in_scope": 20,
        "small_diff": {"applied": False},
        "finders": 4,
        "agents_started": 9,
        "agents_returned": 9,
        "candidates": 10,
        "dedup_dropped": 0,
        "kept": 0,
        "rejected": 0,
        "uncertain": 0,
        "fixed": [],
        "reopened": [],
        "held_back": {
            "decided_suppressed": 0,
            "rejected_suppressed": 0,
            "outside_scope": 0,
            "duplicate_in_round": 0,
        },
        "disagreements": 0,
        "tiebreaks": 0,
        "tiebreak_overturns": 0,
        "severity_splits": 0,
        "decision_flags": 0,
        "decision_flags_dropped": 0,
        "lost_votes": 0,
        "rejected_ids": [],
        "nit_cap": 5,
        "intent_none": False,
        "doc_path": None,
        "suggestions": [],
    }
    base.update(kw)
    return base


def make_state(
    findings: Iterable[dict] = (),
    rounds: Iterable[dict] | None = None,
    *,
    rejected: Iterable[dict] = (),
    **kw: Any,
) -> dict:
    """ST-4 state. `rounds` defaults to a single round 1; `round` follows its length."""
    round_list = list(rounds) if rounds is not None else [make_round(1)]
    finding_list = list(findings)
    base: dict[str, Any] = {
        "v": 1,
        "mode": "code",
        "target": "code",
        "branch": "feature/x",
        "base_ref": "origin/main",
        "base_sha": "abcdef1234567890",
        "head_sha": "04bc9160000000000",
        "tree_sha": "t" * 40,
        "change_id": f"chg-{len(round_list)}",
        "round": len(round_list),
        "last_plan_id": f"plan-{len(round_list)}",
        "file_ids": {},
        "sections": {},
        "rounds": round_list,
        "findings": finding_list,
        "rejected": list(rejected),
        "next_id": len(finding_list) + 1,
        "suggested_rules": [],
    }
    base.update(kw)
    return base
