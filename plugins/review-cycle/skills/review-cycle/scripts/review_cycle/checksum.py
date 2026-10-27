"""Result checksum shared byte-for-byte with workflows/review.js (WF-13)."""

from __future__ import annotations

from collections.abc import Mapping

_FNV_OFFSET = 0x811C9DC5
_FNV_PRIME = 0x01000193
_FIELD = "\x1f"
_RECORD = "\x1e"
_OPTION_FIELD = "\x1d"
_OPTION = "\x1c"


def fnv1a32(s: str) -> str:
    """Return FNV-1a 32-bit over the code points of `s` as 8 lower-case hex digits."""
    h = _FNV_OFFSET
    for ch in s:
        h ^= ord(ch)
        h = (h * _FNV_PRIME) & 0xFFFFFFFF
    return f"{h:08x}"


def _text(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "1" if value else "0"
    return str(value)


def _record(*fields: object) -> str:
    return _FIELD.join(_text(f) for f in fields) + _RECORD


def _get(obj: object, key: str) -> object:
    return obj.get(key) if isinstance(obj, Mapping) else None


def _candidate_record(c: Mapping) -> str:
    broken_by = c.get("broken_by")
    return _record(
        "C",
        *(c.get(k) for k in ("id", "category", "class", "path", "line", "symbol", "snippet")),
        *(c.get(k) for k in ("claim", "trigger", "evidence", "expected", "lens", "finder")),
        _get(broken_by, "path"),
        _get(broken_by, "line"),
        c.get("scope_note"),
        c.get("of_class"),
    )


def _verdict_record(v: Mapping) -> str:
    decision = v.get("needs_decision")
    options = _get(decision, "options")
    joined = _OPTION.join(
        _text(_get(o, "label")) + _OPTION_FIELD + _text(_get(o, "observable"))
        for o in (options if isinstance(options, list) else [])
    )
    return _record(
        "V",
        *(v.get(k) for k in ("item_id", "kind", "role", "slot", "model", "batch", "holds")),
        *(v.get(k) for k in ("severity", "reason", "evidence", "trigger", "prevented_by")),
        _get(decision, "criterion"),
        _get(decision, "before"),
        _get(decision, "after"),
        _get(decision, "intent_quote"),
        joined,
    )


def checksum_text(result: dict) -> str:
    """Serialise candidates, verdicts, dropped and missing records per WF-13."""
    parts = [_candidate_record(c) for c in result.get("candidates", [])]
    parts += [_verdict_record(v) for v in result.get("verdicts", [])]
    parts += [_record("D", d.get("id"), d.get("dup_of")) for d in result.get("dropped", [])]
    parts += [
        _record("M", m.get("item_id"), m.get("role"), m.get("slot"))
        for m in result.get("missing", [])
    ]
    return "".join(parts)


def result_checksum(result: dict) -> str:
    """Return `fnv1a32(checksum_text(result))`."""
    return fnv1a32(checksum_text(result))
