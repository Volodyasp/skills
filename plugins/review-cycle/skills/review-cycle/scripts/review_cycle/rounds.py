"""Round identity and scope decisions (RND-5..RND-15, RPT-18)."""

from __future__ import annotations

import hashlib
import math
from collections.abc import Mapping

from review_cycle.levels import (
    EXPECTED_CANDIDATES,
    LEVELS,
    SMALL_DIFF_MAX_FILES,
    SMALL_DIFF_MAX_LINES,
    VERIFY_BATCH_MAX,
    level_config,
)

_LEVEL_ORDER = tuple(LEVELS)


def change_id(file_ids: Mapping[str, str]) -> str:
    """Return the change identity: sha256 of sorted `path\\x1fdiff-id` lines joined by `\\n`."""
    lines = "\n".join(f"{path}\x1f{file_ids[path]}" for path in sorted(file_ids))
    return hashlib.sha256(lines.encode("utf-8")).hexdigest()


def decide_scope(
    round_n: int,
    full: bool,
    incremental: bool,
    base_changed: bool,
    prev_ids: Mapping[str, str] | None,
    cur_ids: Mapping[str, str],
) -> dict:
    """Choose the scope of round `round_n` (RPT-18).

    Args:
        round_n: number of the round about to run; round 1 is always `full`.
        full: `--full`/`--fresh` was given, or the round is a forced rerun.
        incremental: `--incremental` was given (ignored when `full` wins).
        base_changed: the code base ref changed since the state's last round.
        prev_ids: `state.file_ids` of the last round, or None when missing.
        cur_ids: diff-ids of the branch's files now.

    Returns:
        Dict with `kind` (full|full_base_changed|since|full_fallback), `files`, `deleted`.

    Raises:
        ValueError: round >= 2 with neither `full` nor `incremental` set; the choose step
            (RPT-18) always resolves one of them before a plan is assembled, so a caller
            reaching this is a programming error, not a user input to fall back on.
    """
    if round_n == 1 or full:
        kind = "full_base_changed" if base_changed else "full"
        return {"kind": kind, "files": sorted(cur_ids), "deleted": []}
    if incremental:
        if prev_ids is None:
            return {"kind": "full_fallback", "files": sorted(cur_ids), "deleted": []}
        changed = [path for path, fid in cur_ids.items() if prev_ids.get(path) != fid]
        deleted = [path for path in prev_ids if path not in cur_ids]
        return {"kind": "since", "files": sorted(changed), "deleted": sorted(deleted)}
    raise ValueError("decide_scope: round >= 2 needs full or incremental resolved first")


def level_rank(level: str) -> int:
    """Return `level`'s position in `levels.LEVELS` (low < medium < high < xhigh < max)."""
    return _LEVEL_ORDER.index(level)


def max_earlier_rank(rounds_entries: list[dict]) -> int:
    """Return the highest level rank among `rounds_entries`, or -1 when there are none."""
    if not rounds_entries:
        return -1
    return max(level_rank(r["level"]) for r in rounds_entries)


def estimate_total(
    level: str, mode: str, model: str | None, lines: int, items: int, recheck_n: int
) -> int:
    """Return the RND-15 agent total for `level` reviewing a scope of `lines`/`items`.

    Applies the small-diff finder cut (RND-13) the same way a round's plan would.
    """
    small = mode == "code" and is_small(lines, items)
    cfg = level_config(level, mode, model, small)
    return agent_estimate(cfg, recheck_n)["total"]


def count_noun(n: int, noun: str) -> str:
    """Return `n` with `noun` pluralised (`"1 file"`, `"2 files"`)."""
    return f"{n} {noun}" if n == 1 else f"{n} {noun}s"


def is_small(lines: int, files: int) -> bool:
    """Return True when the scope qualifies for the small-diff finder cut (RND-13)."""
    return lines <= SMALL_DIFF_MAX_LINES and files <= SMALL_DIFF_MAX_FILES


def reconsider_question(round_n: int, findings: list[dict]) -> bool:
    """Return True when the round-4 "reconsider the approach?" question applies (RND-14)."""
    if round_n < 4:
        return False
    return any(
        f["status"] == "open"
        and f["severity"] == "important"
        and f["first_round"] <= 2
        and f["origin"] not in ("pre_existing", "out_of_scope")
        for f in findings
    )


def rerun_unchanged(
    typed_level: str | None, last_round_level: str, full: bool, focus: str | None = None
) -> bool:
    """Return True when unchanged code still starts a new round (RND-7, RPT-19).

    `focus` is never stored, so there is nothing to compare it against: any `--focus` on
    unchanged code forces a rerun, the same as `--full` or a different typed level.
    """
    return (
        full or focus is not None or (typed_level is not None and typed_level != last_round_level)
    )


def agent_estimate(cfg: dict, recheck_n: int) -> dict:
    """Estimate agent counts for a round (RND-15).

    Args:
        cfg: the plan's `level_config`.
        recheck_n: number of open findings to re-check.

    Returns:
        Dict with finders, verifiers, tiebreak, sweep, total.
    """
    batches = math.ceil((EXPECTED_CANDIDATES + recheck_n) / VERIFY_BATCH_MAX)
    votes = len(cfg["votes"])
    finders = len(cfg["finders"])
    verifiers = votes * batches
    tiebreak = batches if cfg["tiebreak"] else 0
    sweep = 1 + votes if cfg["sweep"] else 0
    return {
        "finders": finders,
        "verifiers": verifiers,
        "tiebreak": tiebreak,
        "sweep": sweep,
        "total": finders + verifiers + tiebreak + sweep,
    }
