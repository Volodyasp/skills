"""Workflow result unwrapping and validation (ST-11..ST-13)."""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

from review_cycle.checksum import result_checksum

PROVENANCE = "review-cycle/workflows/review.js"

_CODE_CATEGORIES = (
    "intent",
    "logic",
    "edge-case",
    "concurrency",
    "error-handling",
    "rule",
    "stale",
    "regression",
    "contract",
)
_DOC_CATEGORIES = (
    "ambiguity",
    "contradiction",
    "gap",
    "code-claim",
    "unneeded",
    "inconsistency",
)
_ECHO_FIELDS = ("level", "mode", "finders", "votes", "tiebreak", "recheck_ids")
_CHECKSUM_RE = re.compile(r"[0-9a-f]{8}")


class ResultError(Exception):
    """A result file failed validation; the message is the exact ST-13 text."""


def unwrap(raw: object) -> dict:
    """Return the workflow result from a parsed result file.

    A runtime output file (`result` key, no `provenance` key) is unwrapped; a session-written
    copy is returned as is.

    Raises:
        ResultError: `raw` is not a JSON object.
    """
    if not isinstance(raw, dict):
        raise ResultError("error: result is not a JSON object")
    if "result" in raw and "provenance" not in raw:
        inner = raw["result"]
        if not isinstance(inner, dict):
            raise ResultError("error: result is not a JSON object")
        return inner
    return raw


def _fail(path: str, expected: str) -> ResultError:
    return ResultError(f"error: field {path} must be {expected}")


def _field(obj: Mapping, key: str, path: str) -> Any:
    """Return `obj[key]` or raise the "is missing" error for `path`."""
    if key not in obj:
        raise ResultError(f"error: field {path} is missing")
    return obj[key]


def _is_int(value: object, minimum: int = 0) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= minimum


def _check_str(obj: Mapping, key: str, path: str, *, non_empty: bool = False) -> str:
    value = _field(obj, key, path)
    if not isinstance(value, str) or (non_empty and not value):
        raise _fail(path, "non-empty string" if non_empty else "string")
    return value


def _check_int(obj: Mapping, key: str, path: str, maximum: int | None = None) -> int:
    value = _field(obj, key, path)
    if not _is_int(value) or (maximum is not None and value > maximum):
        raise _fail(path, "non-negative integer" if maximum is None else f"integer 0..{maximum}")
    return value


def _check_enum(obj: Mapping, key: str, path: str, allowed: tuple[str, ...]) -> str:
    value = _field(obj, key, path)
    if value not in allowed:
        raise _fail(path, "string, one of " + ", ".join(repr(a) for a in allowed))
    return value


def _check_list(obj: Mapping, key: str, path: str) -> list:
    value = _field(obj, key, path)
    if not isinstance(value, list):
        raise _fail(path, "array")
    return value


def _check_object(obj: Mapping, key: str, path: str) -> dict:
    value = _field(obj, key, path)
    if not isinstance(value, dict):
        raise _fail(path, "object")
    return value


def _element(items: list, index: int, path: str) -> dict:
    item = items[index]
    if not isinstance(item, dict):
        raise _fail(f"{path}[{index}]", "object")
    return item


def _check_candidate(c: dict, path: str, categories: tuple[str, ...]) -> None:
    _check_str(c, "id", f"{path}.id")
    _check_enum(c, "category", f"{path}.category", categories)
    _check_str(c, "class", f"{path}.class")
    _check_str(c, "path", f"{path}.path", non_empty=True)
    _check_int(c, "line", f"{path}.line")
    _check_str(c, "symbol", f"{path}.symbol")
    _check_str(c, "snippet", f"{path}.snippet")
    _check_str(c, "claim", f"{path}.claim", non_empty=True)
    for key in ("trigger", "evidence", "expected"):
        _check_str(c, key, f"{path}.{key}")
    broken_by = _check_object(c, "broken_by", f"{path}.broken_by")
    _check_str(broken_by, "path", f"{path}.broken_by.path")
    _check_int(broken_by, "line", f"{path}.broken_by.line")
    _check_enum(c, "scope_note", f"{path}.scope_note", ("", "outside-goal"))
    _check_str(c, "lens", f"{path}.lens")
    _check_int(c, "finder", f"{path}.finder")
    _check_str(c, "of_class", f"{path}.of_class")


def _check_decision(v: dict, path: str) -> None:
    nd = _check_object(v, "needs_decision", f"{path}.needs_decision")
    base = f"{path}.needs_decision"
    _check_int(nd, "criterion", f"{base}.criterion", maximum=3)
    for key in ("before", "after", "intent_quote"):
        _check_str(nd, key, f"{base}.{key}")
    options = _check_list(nd, "options", f"{base}.options")
    for i in range(len(options)):
        option = _element(options, i, f"{base}.options")
        _check_str(option, "label", f"{base}.options[{i}].label")
        _check_str(option, "observable", f"{base}.options[{i}].observable")


def _check_verdict(v: dict, path: str) -> None:
    _check_str(v, "item_id", f"{path}.item_id")
    _check_enum(v, "kind", f"{path}.kind", ("new", "recheck"))
    _check_enum(v, "role", f"{path}.role", ("vote", "tiebreak"))
    _check_int(v, "slot", f"{path}.slot")
    _check_str(v, "model", f"{path}.model")
    _check_int(v, "batch", f"{path}.batch")
    if not isinstance(_field(v, "holds", f"{path}.holds"), bool):
        raise _fail(f"{path}.holds", "boolean")
    _check_enum(v, "severity", f"{path}.severity", ("important", "nit", ""))
    for key in ("reason", "evidence", "trigger", "prevented_by"):
        _check_str(v, key, f"{path}.{key}")
    _check_decision(v, path)


def _check_types(result: dict, categories: tuple[str, ...]) -> None:
    candidates = _check_list(result, "candidates", "candidates")
    for i in range(len(candidates)):
        _check_candidate(_element(candidates, i, "candidates"), f"candidates[{i}]", categories)
    verdicts = _check_list(result, "verdicts", "verdicts")
    for i in range(len(verdicts)):
        _check_verdict(_element(verdicts, i, "verdicts"), f"verdicts[{i}]")
    dropped = _check_list(result, "dropped", "dropped")
    for i in range(len(dropped)):
        row = _element(dropped, i, "dropped")
        _check_str(row, "id", f"dropped[{i}].id")
        _check_str(row, "dup_of", f"dropped[{i}].dup_of")
    missing = _check_list(result, "missing", "missing")
    for i in range(len(missing)):
        row = _element(missing, i, "missing")
        _check_str(row, "item_id", f"missing[{i}].item_id")
        _check_enum(row, "role", f"missing[{i}].role", ("vote", "tiebreak"))
        _check_int(row, "slot", f"missing[{i}].slot")
    stats = _check_object(result, "stats", "stats")
    for key in ("agents_started", "agents_returned", "finders_null", "verifiers_null"):
        _check_int(stats, key, f"stats.{key}")
    log = _check_list(result, "log", "log")
    if not all(isinstance(line, str) for line in log):
        raise _fail("log", "array of strings")
    checksum = _field(result, "checksum", "checksum")
    if not isinstance(checksum, str) or not _CHECKSUM_RE.fullmatch(checksum):
        raise _fail("checksum", "8 lower-case hex digits")


def _check_echo(result: dict, args: Mapping) -> None:
    echo = _check_object(result, "echo", "echo")
    expected = {
        "level": args.get("level"),
        "mode": args.get("mode"),
        "finders": args.get("finders"),
        "votes": args.get("votes"),
        "tiebreak": args.get("tiebreak"),
        "recheck_ids": [r["id"] for r in args.get("recheck", [])],
    }
    for name in _ECHO_FIELDS:
        if name not in echo or echo[name] != expected[name]:
            raise ResultError(f"error: result echo differs from plan args: {name}")


def _check_items(result: dict, recheck_ids: list[str], votes: list, has_tiebreak: bool) -> None:
    candidate_ids = [c["id"] for c in result["candidates"]]
    seen: set[str] = set()
    for cid in candidate_ids:
        if cid in seen:
            raise ResultError(f"error: duplicate candidate id {cid}")
        seen.add(cid)
    dropped = {d["id"] for d in result["dropped"]}
    known = (seen - dropped) | set(recheck_ids)
    for v in result["verdicts"]:
        if v["item_id"] not in known:
            raise ResultError(f"error: verdict for unknown item {v['item_id']}")
    for i, v in enumerate(result["verdicts"]):
        expected_kind = "recheck" if v["item_id"] in recheck_ids else "new"
        if v["kind"] != expected_kind:
            raise _fail(f"verdicts[{i}].kind", f"'{expected_kind}' for item {v['item_id']}")
    for v in result["verdicts"]:
        if v["role"] == "vote" and v["slot"] >= len(votes):
            raise ResultError(f"error: vote slot {v['slot']} out of range for {v['item_id']}")
    if not has_tiebreak and any(v["role"] == "tiebreak" for v in result["verdicts"]):
        raise ResultError("error: tie-break verdict but level has no tie-break")
    for i, v in enumerate(result["verdicts"]):
        if v["role"] == "tiebreak" and v["slot"] != 0:
            raise _fail(f"verdicts[{i}].slot", "0 for a tie-break row")


def _check_coverage(result: dict, item_ids: list[str], vote_count: int, has_tiebreak: bool) -> None:
    covered = {(v["item_id"], v["role"], v["slot"]) for v in result["verdicts"]}
    covered |= {(m["item_id"], m["role"], m["slot"]) for m in result["missing"]}
    for item in item_ids:
        for slot in range(vote_count):
            if (item, "vote", slot) not in covered:
                raise ResultError(f"error: verdict coverage incomplete: {item}/vote/{slot}")
        if has_tiebreak:
            holders = sum(
                1
                for v in result["verdicts"]
                if v["item_id"] == item and v["role"] == "vote" and v["holds"]
            )
            if 0 < holders < vote_count and (item, "tiebreak", 0) not in covered:
                raise ResultError(f"error: verdict coverage incomplete: {item}/tiebreak/0")


def validate(result: dict, plan: dict) -> None:
    """Validate `result` against `plan` in ST-12 order.

    Raises:
        ResultError: first failing check, with its exact ST-13 message.
    """
    if result.get("provenance") != PROVENANCE:
        raise ResultError(f"error: result provenance is not {PROVENANCE}")
    version = result.get("v")
    if not _is_int(version) or version != 1:
        raise ResultError(f"error: result version {result.get('v')} not supported")
    if result.get("started") is not True:
        raise ResultError(f"error: workflow did not start: {result.get('reason', '')}")
    if result.get("plan_id") != plan["plan_id"]:
        raise ResultError(
            f"error: result is for plan {result.get('plan_id')}, current plan is {plan['plan_id']}"
        )
    if plan["status"] != "ready":
        raise ResultError(f"error: plan is not ready (status {plan['status']})")
    args = plan["workflow"]["args"]
    _check_echo(result, args)
    categories = _CODE_CATEGORIES if plan["mode"] == "code" else _DOC_CATEGORIES
    _check_types(result, categories)
    votes = args["votes"]
    has_tiebreak = bool(args.get("tiebreak"))
    recheck_ids = [r["id"] for r in args.get("recheck", [])]
    _check_items(result, recheck_ids, votes, has_tiebreak)
    dropped = {d["id"] for d in result["dropped"]}
    verified = [c["id"] for c in result["candidates"] if c["id"] not in dropped]
    _check_coverage(result, verified + recheck_ids, len(votes), has_tiebreak)
    if result_checksum(result) != result["checksum"]:
        raise ResultError("error: result checksum mismatch")
