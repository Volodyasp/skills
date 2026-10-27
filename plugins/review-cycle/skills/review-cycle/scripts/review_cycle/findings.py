"""Finding identity, keep rules, severity and state merging (FND-4..FND-18)."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from typing import Any

from review_cycle.levels import (
    FUZZY_SNIPPET_MIN,
    FUZZY_TEXT_MIN,
    NIT_CAP_DEFAULT,
    RULE_SUGGESTION_REPEATS,
)

_DECISIONS = ("intentional", "wontfix", "wrong", "superseded")
_NIT_CAP_RE = re.compile(
    r"at most (\d+|one|two|three|four|five|six|seven|eight|nine|ten) nits?\b", re.IGNORECASE
)
_NUMBER_WORDS = {
    "one": 1,
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "six": 6,
    "seven": 7,
    "eight": 8,
    "nine": 9,
    "ten": 10,
}
_CLASS_CAP = 80


@dataclass
class MergeContext:
    """Inputs of `merge_round` that are not in plan/result.

    Attributes:
        now: UTC ISO timestamp written to `merged_at` and disposition-free outcome lines.
        file_texts: current text per anchor path; None when the file is gone.
        ranges: changed line ranges per path (`changed_ranges`, code mode, FND-9).
        file_ids: current branch diff-id per path (code) or section hash per heading key
            (document); the source of `anchor_file_id` (ST-5).
        doc_path: repo-relative document path (document mode), else None; copied to
            `round_entry["doc_path"]` for the report header.
        intent_texts: `intent.md` plus linked files at HEAD, for FND-8 criterion 2.
    """

    now: str = ""
    file_texts: dict[str, str | None] = field(default_factory=dict)
    ranges: dict[str, list[tuple[int, int]]] = field(default_factory=dict)
    file_ids: dict[str, str] = field(default_factory=dict)
    intent_texts: list[str] = field(default_factory=list)
    doc_path: str | None = None


@dataclass
class MergeOutcome:
    """What `merge_round` produced for the round just merged.

    Attributes:
        round_entry: the ST-6 entry appended to `state["rounds"]`.
        outcome_lines: ST-7 lines (without `repo`) for findings closed as `fixed` this round.
        votes: every verdict row (votes and tie-break) per finding id, for `round-N.md`.
        rejected: rejected candidates as `{"candidate": <ST-11 item>, "votes": [<verdict>]}`.
        dropped: the result's `dropped` rows (duplicates removed by the workflow).
        log: the result's `log` lines.
    """

    round_entry: dict = field(default_factory=dict)
    outcome_lines: list[dict] = field(default_factory=list)
    votes: dict[str, list[dict]] = field(default_factory=dict)
    rejected: list[dict] = field(default_factory=list)
    dropped: list[dict] = field(default_factory=list)
    log: list[str] = field(default_factory=list)


def _norm_lines(s: str) -> list[str]:
    lines = (" ".join(line.split()) for line in s.split("\n"))
    return [line for line in lines if line]


def _sha256(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def _id_number(fid: str) -> int:
    return int(fid[1:])


def norm_snippet(s: str) -> str:
    """Strip each line, collapse whitespace runs, drop empty lines, join with `\\n`."""
    return "\n".join(_norm_lines(s))


def fingerprint(category: str, path: str, symbol: str, snippet: str) -> str:
    """Return the first 16 hex digits of sha256 over the `\\x1f`-joined fields (snippet normalised)."""
    return _sha256("\x1f".join((category, path, symbol, norm_snippet(snippet))))[:16]


# SequenceMatcher is quadratic; model-written snippets and claims can be long.
_RATIO_MAX_CHARS = 2000


def _ratio(a: str, b: str) -> float:
    return SequenceMatcher(None, a[:_RATIO_MAX_CHARS], b[:_RATIO_MAX_CHARS]).ratio()


def match(cand: dict, findings: list[dict]) -> dict | None:
    """Find the existing finding a candidate repeats.

    Exact fingerprint first; else same path and symbol with fuzzy snippet and class/claim
    similarity. Returns the best hit (ties: lowest id) or None.
    """
    fp = fingerprint(cand["category"], cand["path"], cand["symbol"], cand["snippet"])
    exact = [f for f in findings if f["fingerprint"] == fp]
    if exact:
        return min(exact, key=lambda f: _id_number(f["id"]))
    cand_snippet = norm_snippet(cand["snippet"])
    best: tuple[float, int, dict] | None = None
    for f in findings:
        anchor = f["anchor"]
        if anchor["path"] != cand["path"] or anchor["symbol"] != cand["symbol"]:
            continue
        snippet_ratio = _ratio(norm_snippet(anchor["snippet"]), cand_snippet)
        text_ratio = max(_ratio(f["class"], cand["class"]), _ratio(f["claim"], cand["claim"]))
        if snippet_ratio < FUZZY_SNIPPET_MIN or text_ratio < FUZZY_TEXT_MIN:
            continue
        rank = (-snippet_ratio, _id_number(f["id"]))
        if best is None or rank < (-best[0], best[1]):
            best = (snippet_ratio, _id_number(f["id"]), f)
    return best[2] if best else None


def _holds(verdict: dict | None) -> bool:
    return verdict is not None and bool(verdict["holds"])


def keep_outcome(rule: str, votes: list[dict | None], tiebreak: dict | None) -> str:
    """Apply a keep rule to a new item's votes.

    Args:
        rule: all2 | all2_tiebreak | maj3.
        votes: one verdict per slot; None for a missing vote.
        tiebreak: the tie-break verdict, or None if absent or not run.

    Returns:
        "confirmed", "uncertain" or "rejected".

    Raises:
        ValueError: unknown rule.
    """
    if rule not in ("all2", "all2_tiebreak", "maj3"):
        raise ValueError(f"unknown keep rule {rule!r}")
    returned = [v for v in votes if v is not None]
    if not returned and tiebreak is None:
        return "uncertain"
    holding = sum(1 for v in returned if v["holds"])
    missing = len(votes) - len(returned)
    if rule == "maj3":
        return "confirmed" if holding >= 2 else "uncertain" if holding == 1 else "rejected"
    if holding == len(votes):
        return "confirmed"
    if rule == "all2":
        return "uncertain" if holding == 1 and missing == 1 else "rejected"
    if holding == 0:
        return "rejected"
    if tiebreak is None:
        return "uncertain"
    return "confirmed" if tiebreak["holds"] else "rejected"


def recheck_outcome(
    rule: str, votes: list[dict | None], tiebreak: dict | None, code_moved: bool
) -> tuple[str, str | None]:
    """Decide a re-checked finding (FND-18).

    Returns:
        (status, verdict) where status is "open" or "fixed" and verdict is
        "confirmed", "uncertain" or None when the finding is unchanged.
    """
    returned = [v for v in (*votes, tiebreak) if v is not None]
    if not returned:
        return "open", None
    if any(v["holds"] for v in returned):
        confirmed = keep_outcome(rule, votes, tiebreak) == "confirmed"
        return "open", "confirmed" if confirmed else "uncertain"
    if code_moved:
        return "fixed", None
    return "open", "uncertain"


def severity_of(confirming: list[dict]) -> tuple[str, bool]:
    """Return ("important" | "nit", split) from the confirming verdicts (FND-7)."""
    severities = {v["severity"] for v in confirming if v["severity"]}
    severity = "important" if "important" in severities else "nit"
    return severity, len(severities) > 1


def _norm_ws(s: str) -> str:
    return " ".join(s.split())


def _flag_valid(flag: dict, intent_texts: list[str]) -> bool:
    criterion = flag["criterion"]
    if criterion == 1:
        return bool(flag["before"]) and bool(flag["after"]) and flag["before"] != flag["after"]
    if criterion == 2:
        quote = _norm_ws(flag["intent_quote"])
        return bool(quote) and any(quote in _norm_ws(text) for text in intent_texts)
    if criterion == 3:
        complete = [o for o in flag["options"] if o["label"] and o["observable"]]
        return len(complete) >= 2
    return False


def _real_flags(flags: list[dict]) -> list[dict]:
    return [f for f in flags if f["criterion"] in (1, 2, 3)]


def validate_decision(flags: list[dict], intent_texts: list[str]) -> dict | None:
    """Return the valid needs-decision flag with the lowest criterion, or None (FND-8)."""
    valid = [f for f in _real_flags(flags) if _flag_valid(f, intent_texts)]
    return min(valid, key=lambda f: f["criterion"]) if valid else None


def locate_anchor(file_text: str | None, snippet: str, fallback: int) -> int:
    """Return the 1-based line of the first normalised match of `snippet`, else `fallback`."""
    wanted = _norm_lines(snippet)
    if file_text is None or not wanted:
        return fallback
    numbered = [
        (number, " ".join(line.split()))
        for number, line in enumerate(file_text.split("\n"), start=1)
        if line.strip()
    ]
    texts = [text for _, text in numbered]
    for start in range(len(texts) - len(wanted) + 1):
        if texts[start : start + len(wanted)] == wanted:
            return numbered[start][0]
    return fallback


def snippet_present(file_text: str | None, snippet_hash: str, snippet_lines: int) -> bool:
    """Return True when some window of `snippet_lines` normalised lines hashes to the given hash.

    A missing file (`None`) is False.
    """
    if file_text is None or snippet_lines <= 0:
        return False
    lines = _norm_lines(file_text)
    return any(
        _sha256("\n".join(lines[i : i + snippet_lines])) == snippet_hash
        for i in range(len(lines) - snippet_lines + 1)
    )


def _in_ranges(line: int, spans: list[tuple[int, int]]) -> bool:
    return any(start <= line <= end for start, end in spans)


def origin_code(path: str, line: int, broken_by: dict, ranges: dict) -> str:
    """Classify a code finding as introduced, broken_by_change or pre_existing (FND-9)."""
    if _in_ranges(line, ranges.get(path, [])):
        return "introduced"
    cause = broken_by.get("path", "")
    if cause and _in_ranges(broken_by.get("line", 0), ranges.get(cause, [])):
        return "broken_by_change"
    return "pre_existing"


def nit_cap(review_md: str | None) -> int:
    """Return the nit cap stated in REVIEW.md, or `NIT_CAP_DEFAULT` (FND-13)."""
    found = _NIT_CAP_RE.search(review_md or "")
    if not found:
        return NIT_CAP_DEFAULT
    word = found.group(1).lower()
    return _NUMBER_WORDS[word] if word in _NUMBER_WORDS else int(word)


def section_of(f: dict, round_n: int) -> str | None:
    """Return the report section a finding belongs to in round `round_n`, or None (FND-14)."""
    if f["status"] != "open":
        return "reopen" if f["reopen_round"] == round_n else None
    if f["hidden_reason"]:
        return None
    if f["origin"] in ("pre_existing", "out_of_scope"):
        return f["origin"]
    if f["needs_decision"]:
        return "needs_decision"
    if f["verdict"] == "uncertain":
        return "uncertain"
    return "agent_can_fix" if f["severity"] == "important" else "nit"


def _outcome_line(state: dict, f: dict, now: str, level: str | None = None) -> dict:
    rounds = state["rounds"]
    if level is None and rounds:
        level = rounds[-1]["level"]
    return {
        "ts": now,
        "branch": state.get("branch"),
        "mode": state.get("mode"),
        "level": level,
        "finding_id": f["id"],
        "category": f["category"],
        "class": f["class"][:_CLASS_CAP],
        "severity": f["severity"],
        "status": f["status"],
        "response_type": f["response_type"],
        "round": state["round"],
        "first_round": f["first_round"],
        "moved_from_decision": f["moved_from_decision"],
    }


def _decide(state: dict, f: dict, verb: str, reason: str | None, now: str) -> tuple[dict, str]:
    if f["status"] == "open":
        response_type = section_of(f, state["round"])
    elif f["status"] == "fixed":
        response_type = "fixed"
    else:
        response_type = f["response_type"]
    f["status"] = verb
    f["response_type"] = response_type
    f["disposition"] = {
        "reason": reason or "",
        "at": now,
        "snippet_hash": _sha256(norm_snippet(f["anchor"]["snippet"])),
    }
    return _outcome_line(state, f, now), f"{f['id']} {verb}"


def apply_mark(
    state: dict, fid: str, verb: str, reason: str | None, now: str
) -> tuple[dict, dict | None, str]:
    """Apply a mark verb to finding `fid` (FND-15).

    `state` is updated in place and returned.

    Returns:
        (state, outcome line or None, message). A refused transition raises ValueError with
        the CLI error text.
    """
    f = next((x for x in state["findings"] if x["id"] == fid), None)
    if f is None:
        raise ValueError(f"no finding {fid}")
    status = f["status"]
    if verb in _DECISIONS:
        line, message = _decide(state, f, verb, reason, now)
        return state, line, message
    if verb == "open":
        if status == "open":
            return state, None, f"{fid} is already open"
        f["status"] = "open"
        f["disposition"] = None
        f["reopen_round"] = None
        return state, None, f"{fid} open"
    if status != "open":
        raise ValueError(f"{fid} is {status}, not open")
    if not f["needs_decision"]:
        raise ValueError(f'{fid} is not in "needs your decision"')
    f["needs_decision"] = None
    f["moved_from_decision"] = True
    return state, None, f"{fid} fix"


def rule_suggestions(outcomes: list[dict], repo: str, done: set[str]) -> list[dict]:
    """Return REVIEW.md rule suggestions for classes marked wrong repeatedly (FND-16).

    Args:
        outcomes: all outcome records.
        repo: repository identity as written in outcomes.
        done: classes already suggested.

    Returns:
        Dicts with `class` and `text`.
    """
    groups: list[tuple[str, int]] = []
    for o in outcomes:
        if o["repo"] != repo or o["status"] != "wrong":
            continue
        for i, (first, count) in enumerate(groups):
            if _ratio(first, o["class"]) >= FUZZY_SNIPPET_MIN:
                groups[i] = (first, count + 1)
                break
        else:
            groups.append((o["class"], 1))
    return [
        {
            "class": cls,
            "text": (
                f'Rule suggestion: "{cls}" marked wrong {count}× in this repo. '
                f"A REVIEW.md line such as: Do not report {cls}."
            ),
        }
        for cls, count in groups
        if count >= RULE_SUGGESTION_REPEATS and cls not in done
    ]


_SEVERITY_RANK = {"nit": 0, "important": 1}


@dataclass
class _Item:
    """The verdict rows of one verified item, by role."""

    rows: list[dict]
    votes: list[dict | None]
    tiebreak: dict | None

    @property
    def confirming(self) -> list[dict]:
        return [v for v in (*self.votes, self.tiebreak) if v is not None and v["holds"]]


def _collect_item(item_id: str, verdicts: list[dict], slots: int) -> _Item:
    rows = [v for v in verdicts if v["item_id"] == item_id]
    votes: list[dict | None] = [None] * slots
    tiebreak: dict | None = None
    for row in rows:
        if row["role"] == "tiebreak":
            tiebreak = tiebreak or row
        elif votes[row["slot"]] is None:
            votes[row["slot"]] = row
    return _Item(rows, votes, tiebreak)


def _anchor_key(mode: str, anchor: dict) -> str:
    """Key of `MergeContext.file_ids` for an anchor: heading key in documents, else the path."""
    return anchor["symbol"] if mode == "document" else anchor["path"]


def _refresh_anchor(f: dict, cand: dict, mode: str, ctx: MergeContext) -> None:
    path = cand["path"]
    f["anchor"]["line"] = locate_anchor(ctx.file_texts.get(path), cand["snippet"], cand["line"])
    f["anchor"]["snippet"] = cand["snippet"]
    f["anchor_file_id"] = ctx.file_ids.get(_anchor_key(mode, f["anchor"]), "")


def _held_back() -> dict[str, int]:
    return {
        "decided_suppressed": 0,
        "rejected_suppressed": 0,
        "outside_scope": 0,
        "duplicate_in_round": 0,
    }


class _Merger:
    """One `merge_round` run: owns the counters of the round entry."""

    def __init__(self, state: dict, plan: dict, result: dict, ctx: MergeContext) -> None:
        self.state, self.plan, self.result, self.ctx = state, plan, result, ctx
        self.n: int = plan["round"]
        self.mode: str = plan["mode"]
        config = plan["level_config"]
        self.rule: str = config["keep_rule"]
        self.slots: int = len(config["votes"])
        self.out = MergeOutcome(
            dropped=list(result["dropped"]),
            log=list(result["log"]),
        )
        self.held_back = _held_back()
        self.reopened: list[str] = []
        self.fixed: list[str] = []
        self.rejected_ids: list[str] = []
        self.counts = {
            "kept": 0,
            "rejected": 0,
            "uncertain": 0,
            "severity_splits": 0,
            "decision_flags": 0,
            "decision_flags_dropped": 0,
            "disagreements": 0,
            "tiebreaks": 0,
            "tiebreak_overturns": 0,
        }
        self.created: set[str] = set()

    def run(self) -> MergeOutcome:
        self.state["round"] = self.n
        self._stats_of_all_items()
        for entry in self.plan["recheck"]:
            self._recheck(entry["id"])
        dropped = {d["id"] for d in self.result["dropped"]}
        for cand in self.result["candidates"]:
            if cand["id"] not in dropped:
                self._new_item(cand)
        self._clear_hidden()
        self._finish()
        return self.out

    def _item(self, item_id: str) -> _Item:
        return _collect_item(item_id, self.result["verdicts"], self.slots)

    def _stats_of_all_items(self) -> None:
        """Count disagreements and tie-breaks over every verified item (ST-6)."""
        dropped = {d["id"] for d in self.result["dropped"]}
        ids = [c["id"] for c in self.result["candidates"] if c["id"] not in dropped]
        ids += [r["id"] for r in self.plan["recheck"]]
        for item_id in ids:
            item = self._item(item_id)
            returned = [v for v in item.votes if v is not None]
            if len({bool(v["holds"]) for v in returned}) > 1:
                self.counts["disagreements"] += 1
            if item.tiebreak is not None:
                self.counts["tiebreaks"] += 1
                last_slot = item.votes[-1]
                if last_slot is not None and bool(item.tiebreak["holds"]) != bool(
                    last_slot["holds"]
                ):
                    self.counts["tiebreak_overturns"] += 1

    def _note_severity(self, item: _Item) -> tuple[str, list[dict]]:
        severity, split = severity_of(item.confirming)
        if split:
            self.counts["severity_splits"] += 1
        votes = [
            {"model": v["model"], "severity": v["severity"], "reason": v["reason"]}
            for v in item.confirming
            if v["severity"]
        ]
        return severity, votes

    def _recheck(self, fid: str) -> None:
        f = next((x for x in self.state["findings"] if x["id"] == fid), None)
        if f is None or f["status"] != "open":
            return
        item = self._item(fid)
        self.out.votes.setdefault(fid, []).extend(item.rows)
        key = _anchor_key(self.mode, f["anchor"])
        path = f["anchor"]["path"]
        snippet_hash = _sha256(norm_snippet(f["anchor"]["snippet"]))
        lines = len(_norm_lines(f["anchor"]["snippet"]))
        moved = (
            not snippet_present(self.ctx.file_texts.get(path), snippet_hash, lines)
            or self.ctx.file_ids.get(key, "") != f["anchor_file_id"]
        )
        status, verdict = recheck_outcome(self.rule, item.votes, item.tiebreak, moved)
        if status == "fixed":
            f["status"] = "fixed"
            f["response_type"] = "fixed"
            self.fixed.append(fid)
            line = _outcome_line(self.state, f, self.ctx.now, self.plan["level"])
            self.out.outcome_lines.append(line)
        elif verdict is not None:
            f["verdict"] = verdict
            if item.confirming:
                severity, _ = self._note_severity(item)
                if _SEVERITY_RANK[severity] > _SEVERITY_RANK[f["severity"]]:
                    f["severity"] = severity
                f["last_seen_round"] = self.n
                f["anchor"]["line"] = locate_anchor(
                    self.ctx.file_texts.get(path), f["anchor"]["snippet"], f["anchor"]["line"]
                )
                f["anchor_file_id"] = self.ctx.file_ids.get(key, "")

    def _new_item(self, cand: dict) -> None:
        item = self._item(cand["id"])
        outcome = keep_outcome(self.rule, item.votes, item.tiebreak)
        if outcome == "rejected":
            self._reject(cand, item)
            return
        self.counts["kept" if outcome == "confirmed" else "uncertain"] += 1
        hit = match(cand, self.state["findings"])
        if hit is not None:
            self.out.votes.setdefault(hit["id"], []).extend(item.rows)
            self._merge_into(hit, cand)
            return
        fp = fingerprint(cand["category"], cand["path"], cand["symbol"], cand["snippet"])
        if any(r["fingerprint"] == fp for r in self.state["rejected"]):
            self.held_back["rejected_suppressed"] += 1
            return
        self._create(cand, item, outcome, fp)

    def _reject(self, cand: dict, item: _Item) -> None:
        self.counts["rejected"] += 1
        self.rejected_ids.append(cand["id"])
        self.out.rejected.append({"candidate": cand, "votes": item.rows})
        fp = fingerprint(cand["category"], cand["path"], cand["symbol"], cand["snippet"])
        known = next((r for r in self.state["rejected"] if r["fingerprint"] == fp), None)
        if known is not None:
            known["round"] = self.n
            return
        normalised = norm_snippet(cand["snippet"])
        self.state["rejected"].append(
            {
                "fingerprint": fp,
                "category": cand["category"],
                "class": cand["class"],
                "path": cand["path"],
                "symbol": cand["symbol"],
                "line": cand["line"],
                "claim": cand["claim"],
                "snippet_hash": _sha256(normalised),
                "snippet_lines": len(_norm_lines(cand["snippet"])),
                "round": self.n,
            }
        )

    def _merge_into(self, f: dict, cand: dict) -> None:
        if f["id"] in self.created:
            self.held_back["duplicate_in_round"] += 1
        status = f["status"]
        if status == "open":
            f["last_seen_round"] = self.n
        elif status == "fixed":
            f["status"] = "open"
            f["last_seen_round"] = self.n
            self.reopened.append(f["id"])
        else:
            changed = _sha256(norm_snippet(cand["snippet"])) != (f["disposition"] or {}).get(
                "snippet_hash"
            )
            if changed and f["reopen_round"] is None:
                f["reopen_round"] = self.n
            else:
                self.held_back["decided_suppressed"] += 1
        _refresh_anchor(f, cand, self.mode, self.ctx)

    def _origin(self, cand: dict, line: int) -> str:
        if self.mode == "code":
            return origin_code(cand["path"], line, cand["broken_by"], self.ctx.ranges)
        since = self.plan["scope"]["kind"] == "since"
        outside = since and cand["symbol"] not in self.plan["scope"]["sections"]
        return "out_of_scope" if cand["scope_note"] == "outside-goal" or outside else "in_scope"

    def _decision(self, item: _Item) -> dict | None:
        flags = _real_flags([v["needs_decision"] for v in item.confirming])
        valid = validate_decision(flags, self.ctx.intent_texts)
        self.counts["decision_flags_dropped"] += sum(
            1 for flag in flags if not _flag_valid(flag, self.ctx.intent_texts)
        )
        if valid is not None:
            self.counts["decision_flags"] += 1
        return valid

    def _create(self, cand: dict, item: _Item, outcome: str, fp: str) -> None:
        fid = f"F{self.state['next_id']}"
        self.state["next_id"] += 1
        line = locate_anchor(self.ctx.file_texts.get(cand["path"]), cand["snippet"], cand["line"])
        severity, severity_votes = self._note_severity(item)
        anchor = {
            "path": cand["path"],
            "line": line,
            "symbol": cand["symbol"],
            "snippet": cand["snippet"],
        }
        hidden = (
            "outside_scope"
            if self.mode == "code"
            and self.plan["scope"]["kind"] == "since"
            and cand["path"] not in self.plan["scope"]["files"]
            else None
        )
        if hidden:
            self.held_back["outside_scope"] += 1
        self.state["findings"].append(
            {
                "id": fid,
                "fingerprint": fp,
                "category": cand["category"],
                "class": cand["class"],
                "severity": severity,
                "severity_votes": severity_votes,
                "verdict": outcome,
                "origin": self._origin(cand, line),
                "anchor": anchor,
                "anchor_file_id": self.ctx.file_ids.get(_anchor_key(self.mode, anchor), ""),
                "claim": cand["claim"],
                "evidence": cand["evidence"],
                "trigger": cand["trigger"],
                "expected": cand["expected"],
                "status": "open",
                "disposition": None,
                "needs_decision": self._decision(item),
                "first_round": self.n,
                "last_seen_round": self.n,
                "response_type": None,
                "reopen_round": None,
                "moved_from_decision": False,
                "hidden_reason": hidden,
            }
        )
        self.created.add(fid)
        self.out.votes[fid] = list(item.rows)

    def _clear_hidden(self) -> None:
        scope_files = set(self.plan["scope"]["files"])
        for f in self.state["findings"]:
            if f["hidden_reason"] == "outside_scope" and f["anchor"]["path"] in scope_files:
                f["hidden_reason"] = None

    def _finish(self) -> None:
        plan, result, state = self.plan, self.result, self.state
        state.update(
            last_plan_id=plan["plan_id"],
            head_sha=plan["head_sha"],
            tree_sha=plan["tree_sha"],
            change_id=plan["change_id"],
            file_ids=dict(plan["file_ids"]),
        )
        state.update(
            mode=plan["mode"],
            branch=plan["branch"],
            base_ref=plan["base_ref"],
            base_sha=plan["merge_base"],
        )
        if self.mode == "document":
            state["sections"] = dict(self.ctx.file_ids)
        stats = result["stats"]
        self.out.round_entry = {
            "n": self.n,
            "level": plan["level"],
            "model_override": plan.get("model_override"),
            "plan_id": plan["plan_id"],
            "created_at": plan["created_at"],
            "merged_at": self.ctx.now,
            "base_sha": plan["merge_base"],
            "head_sha": plan["head_sha"],
            "tree_sha": plan["tree_sha"],
            "change_id": plan["change_id"],
            "scope_kind": plan["scope"]["kind"],
            "files_in_scope": len(plan["scope"]["files"]),
            "lines_in_scope": plan["scope"]["lines"],
            "small_diff": plan["small_diff"],
            "finders": len(plan["level_config"]["finders"]),
            "agents_started": stats["agents_started"],
            "agents_returned": stats["agents_returned"],
            "candidates": len(result["candidates"]),
            "dedup_dropped": len(result["dropped"]),
            "kept": self.counts["kept"],
            "rejected": self.counts["rejected"],
            "uncertain": self.counts["uncertain"],
            "fixed": self.fixed,
            "reopened": self.reopened,
            "held_back": self.held_back,
            "disagreements": self.counts["disagreements"],
            "tiebreaks": self.counts["tiebreaks"],
            "tiebreak_overturns": self.counts["tiebreak_overturns"],
            "severity_splits": self.counts["severity_splits"],
            "decision_flags": self.counts["decision_flags"],
            "decision_flags_dropped": self.counts["decision_flags_dropped"],
            "lost_votes": len(result["missing"]),
            "rejected_ids": self.rejected_ids,
            "nit_cap": plan["review_md"]["nit_cap"],
            "intent_none": plan["intent"]["none"],
            "doc_path": self.ctx.doc_path,
            "suggestions": [],
        }
        state["rounds"].append(self.out.round_entry)


_LONE_SURROGATE = re.compile("[\ud800-\udfff]")


def _replace_lone_surrogates(value: Any) -> Any:
    """Return `value` with lone surrogates in every string replaced by U+FFFD.

    The checksum is computed on the raw text; afterwards such strings could not be hashed or
    written as UTF-8.
    """
    if isinstance(value, str):
        return _LONE_SURROGATE.sub("\ufffd", value)
    if isinstance(value, list):
        return [_replace_lone_surrogates(v) for v in value]
    if isinstance(value, dict):
        return {k: _replace_lone_surrogates(v) for k, v in value.items()}
    return value


def merge_round(state: dict, plan: dict, result: dict, ctx: MergeContext) -> MergeOutcome:
    """Merge a validated workflow result into `state` in place (FND-10..FND-12).

    Returns:
        The round's statistics and outcome lines.
    """
    return _Merger(state, plan, _replace_lone_surrogates(result), ctx).run()
