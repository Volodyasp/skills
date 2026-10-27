"""Rendering of reports, round files and finding details (RPT-1..RPT-9)."""

from __future__ import annotations

from dataclasses import dataclass, field

from review_cycle.findings import MergeOutcome, section_of

_CHUNK = 32
_CLASS_SHORT = 60
_SHOWN_ORDER = ("needs_decision", "agent_can_fix", "uncertain", "nit", "other")


@dataclass
class _Layout:
    """The findings of the latest round, grouped into report sections (RPT-4)."""

    sections: dict[str, list[dict]] = field(default_factory=dict)
    nits_over_cap: int = 0
    hidden: int = 0
    nit_total: int = 0

    def shown(self) -> list[dict]:
        return [f for name in _SHOWN_ORDER for f in self.sections.get(name, [])]


def _position(f: dict) -> tuple[str, int]:
    return f["anchor"]["path"], f["anchor"]["line"]


def _latest(state: dict) -> dict:
    return state["rounds"][-1]


def _layout(state: dict) -> _Layout:
    latest = _latest(state)
    round_n = latest["n"]
    grouped: dict[str, list[dict]] = {name: [] for name in (*_SHOWN_ORDER, "reopen")}
    layout = _Layout()
    for f in state["findings"]:
        if f["status"] == "open" and f["hidden_reason"]:
            layout.hidden += 1
        section = section_of(f, round_n)
        if section is None:
            continue
        key = "other" if section in ("pre_existing", "out_of_scope") else section
        grouped[key].append(f)
    for items in grouped.values():
        items.sort(key=_position)
    nits = sorted(grouped["nit"], key=lambda f: (-f["first_round"], *_position(f)))
    cap = latest["nit_cap"]
    layout.nit_total = len(nits)
    layout.nits_over_cap = max(0, len(nits) - cap)
    grouped["nit"] = nits[:cap]
    layout.sections = grouped
    return layout


def _since(state: dict) -> str:
    latest = _latest(state)
    if state["mode"] == "document":
        return f"doc {latest['doc_path']}"
    if latest["scope_kind"] != "since":
        return f"vs {state['base_ref']}@{latest['base_sha'][:7]}"
    return f"since {state['rounds'][-2]['head_sha'][:7]}"


def _header(state: dict) -> str:
    latest = _latest(state)
    parts = [
        f"review-cycle · round {latest['n']} · {latest['level']} · {_since(state)}",
        f"{latest['agents_returned']} agents",
    ]
    if latest["model_override"]:
        parts.append(f"model {latest['model_override']}")
    small = latest["small_diff"]
    if small["applied"]:
        parts.append(f"small diff: {small['finders_to']} finders")
    return " · ".join(parts)


def _other_label(state: dict) -> str:
    return "Out of scope" if state["mode"] == "document" else "Pre-existing"


def _count_line(state: dict, layout: _Layout) -> str:
    sections = layout.sections
    parts = [
        f"{len(sections['needs_decision'])} needs your decision",
        f"{len(sections['agent_can_fix'])} agent can fix",
        f"{layout.nit_total} Nit",
        f"{len(sections['other'])} {_other_label(state)}",
        f"{_latest(state)['rejected']} rejected",
    ]
    if sections["uncertain"]:
        parts.append(f"{len(sections['uncertain'])} Uncertain")
    return " · ".join(parts)


def _closed_line(state: dict, layout: _Layout) -> str:
    latest = _latest(state)
    parts = []
    if latest["fixed"]:
        parts.append(f"Closed since round {latest['n'] - 1}: {', '.join(latest['fixed'])} (fixed)")
    not_shown = []
    if layout.nits_over_cap:
        not_shown.append(f"{layout.nits_over_cap} nits over the cap")
    if layout.hidden:
        not_shown.append(f"{layout.hidden} outside this re-review")
    if not_shown:
        parts.append("not shown: " + ", ".join(not_shown))
    return " · ".join(parts)


def _item_line(f: dict, suffix: str = "") -> str:
    anchor = f["anchor"]
    return f" {f['id'].ljust(3)} {anchor['path']}:{anchor['line']} · {f['claim']}{suffix}"


def _why_you(d: dict) -> str:
    criterion = d["criterion"]
    if criterion == 1:
        return f"the fix changes {d['before']} → {d['after']}"
    if criterion == 2:
        return f"contradicts stated intent: “{d['intent_quote']}”"
    return "fix options differ in behaviour"


def _options_line(d: dict) -> str:
    labels = [o["label"] for o in d["options"]] if d["criterion"] == 3 else []
    return " · ".join([*labels, "mark intentional"])


def _decision_item(f: dict) -> str:
    d = f["needs_decision"]
    tag = " (uncertain)" if f["verdict"] == "uncertain" else ""
    lines = [_item_line(f, tag)]
    if f["trigger"]:
        lines.append(f"     Trigger:  {f['trigger']}")
    if f["evidence"]:
        lines.append(f"     Evidence: {f['evidence']}")
    lines.append(f"     Why you:  {_why_you(d)}")
    lines.append(f"     Options:  {_options_line(d)}")
    return "\n".join(lines)


def _block(heading: str, lines: list[str]) -> str:
    return "\n".join([heading, *lines])


def _section_blocks(state: dict, layout: _Layout) -> list[str]:
    s = layout.sections
    blocks = []
    if s["needs_decision"]:
        blocks.append(
            _block("Needs your decision", [_decision_item(f) for f in s["needs_decision"]])
        )
    if s["agent_can_fix"]:
        lines = [_item_line(f, f" (class: {f['class']})") for f in s["agent_can_fix"]]
        blocks.append(_block("Agent can fix", lines))
    for name, label in (
        ("uncertain", "Uncertain"),
        ("nit", "Nit"),
        ("other", _other_label(state)),
    ):
        if s[name]:
            blocks.append(_block(f"{label} ({len(s[name])})", [_item_line(f) for f in s[name]]))
    if s["reopen"]:
        lines = [
            f" {f['id']} ({f['status']}) code changed — reopen with /review-cycle {f['id']} open"
            for f in s["reopen"]
        ]
        blocks.append(_block("Reopen?", lines))
    return blocks


def render_report(state: dict, *, no_change_of: int | None = None) -> str:
    """Render the CLI report for the latest round in `state`.

    Args:
        state: parsed `state.json`.
        no_change_of: round number to announce as "No code change since round N" (RND-7), or None.
    """
    latest = _latest(state)
    layout = _layout(state)
    sections = layout.sections
    head = [_header(state), _count_line(state, layout)]
    closed = _closed_line(state, layout)
    if closed:
        head.append(closed)
    blocks = ["\n".join(head)]
    if not (sections["needs_decision"] or sections["agent_can_fix"] or sections["uncertain"]):
        blocks.append("Nothing to fix.")
    if latest["intent_none"]:
        blocks.append("No stated intent: the intent lens used commit messages only.")
    blocks += _section_blocks(state, layout)
    if latest["suggestions"]:
        blocks.append("\n".join(latest["suggestions"]))
    shown = layout.shown()
    if shown:
        blocks.append(f"Details: /review-cycle show {shown[0]['id']} (or ask in this session)")
    text = "\n\n".join(blocks) + "\n"
    if no_change_of is not None:
        text = f"No code change since round {no_change_of} — not a new round.\n" + text
    return text


def _cell(text: object) -> str:
    return str(text).replace("|", "\\|").replace("\n", " ")


def _vote_table(rows: list[dict]) -> list[str]:
    lines = ["| model | role | holds | severity | reason |", "|---|---|---|---|---|"]
    for v in rows:
        cells = (v["model"], v["role"], "yes" if v["holds"] else "no", v["severity"], v["reason"])
        lines.append("| " + " | ".join(_cell(c) for c in cells) + " |")
    return lines


def _plain(value: object) -> str:
    """Render a stored value for people: null and empty as `-`, booleans as `yes`/`no`."""
    if value is None or value == "":
        return "-"
    if isinstance(value, bool):
        return "yes" if value else "no"
    return str(value)


def _field_lines(f: dict) -> list[str]:
    """Every ST-5 field of a finding as `name: value` lines."""
    anchor = f["anchor"]
    lines = [
        f"id: {_plain(f['id'])}",
        f"fingerprint: {_plain(f['fingerprint'])}",
        f"class: {_plain(f['class'])}",
        f"category: {_plain(f['category'])}",
        f"severity: {_plain(f['severity'])}",
        f"verdict: {_plain(f['verdict'])}",
        f"origin: {_plain(f['origin'])}",
        f"status: {_plain(f['status'])}",
        f"anchor: {anchor['path']}:{anchor['line']} (symbol: {_plain(anchor['symbol'])})",
        f"anchor snippet: {_plain(anchor['snippet'])}",
        f"anchor_file_id: {_plain(f['anchor_file_id'])}",
        f"claim: {_plain(f['claim'])}",
        f"trigger: {_plain(f['trigger'])}",
        f"evidence: {_plain(f['evidence'])}",
        f"expected: {_plain(f['expected'])}",
        f"first_round: {_plain(f['first_round'])}",
        f"last_seen_round: {_plain(f['last_seen_round'])}",
        f"response_type: {_plain(f['response_type'])}",
        f"reopen_round: {_plain(f['reopen_round'])}",
        f"moved_from_decision: {_plain(f['moved_from_decision'])}",
        f"hidden_reason: {_plain(f['hidden_reason'])}",
    ]
    lines += [
        f"severity vote: {v['model']} {v['severity']} — {_plain(v['reason'])}"
        for v in f["severity_votes"]
    ]
    d = f["needs_decision"]
    if d:
        lines.append(f"needs_decision: criterion {d['criterion']} — {_why_you(d)}")
        lines.append(f"  before: {_plain(d['before'])} · after: {_plain(d['after'])}")
        lines.append(f"  intent quote: {_plain(d['intent_quote'])}")
        lines += [f"  option: {o['label']} → {o['observable']}" for o in d["options"]]
    disposition = f["disposition"]
    if disposition:
        lines.append(
            f"disposition: {disposition['reason']} (at {disposition['at']},"
            f" snippet_hash {disposition['snippet_hash']})"
        )
    return lines


def _finding_md(f: dict, rows: list[dict]) -> list[str]:
    lines = [f"### {f['id']} · {f['class']}", *[f"- {line}" for line in _field_lines(f)]]
    if rows:
        lines += ["", *_vote_table(rows)]
    return [*lines, ""]


def _handoff_md(findings: list[dict]) -> list[str]:
    lines = ["## Hand-off for the coding flow", ""]
    for f in findings:
        lines += [
            f"### {f['id']} · {f['class']}",
            f"Problem: {f['claim']}",
            f"Evidence: {f['evidence']}",
            f"Expected behaviour: {f['expected']}",
            f"Class: every instance of {f['class']}",
            "",
        ]
    return lines


def render_round_md(state: dict, outcome: MergeOutcome) -> str:
    """Render `round-N.md` for the round just merged, including the coding-flow hand-off."""
    layout = _layout(state)
    round_n = _latest(state)["n"]
    lines = [_header(state), _count_line(state, layout), "", "## Findings", ""]
    for f in state["findings"]:
        lines += _finding_md(f, outcome.votes.get(f["id"], []))
    lines += ["## Rejected candidates", ""]
    for item in outcome.rejected:
        lines += [f"### {item['candidate']['id']} · {item['candidate']['claim']}"]
        lines += [*_vote_table(item["votes"]), ""]
    lines += ["## Dropped duplicates", ""]
    lines += [f"- {d['id']} duplicates {d['dup_of']}" for d in outcome.dropped]
    lines += ["", "## Log", ""]
    lines += [f"- {entry}" for entry in outcome.log]
    lines.append("")
    to_fix = [f for f in state["findings"] if section_of(f, round_n) == "agent_can_fix"]
    lines += _handoff_md(to_fix)
    return "\n".join(lines)


def render_show(state: dict, fid: str) -> str:
    """Render every field, vote history and disposition of finding `fid`.

    Raises:
        ValueError: `fid` is not a finding of `state`.
    """
    f = next((x for x in state["findings"] if x["id"] == fid), None)
    if f is None:
        raise ValueError(f"no finding {fid}")
    lines = [f"{fid} · {f['class']}", *_field_lines(f)]
    verbs = f"/review-cycle {fid} intentional|wontfix|wrong|superseded <reason> · {fid} open"
    if section_of(f, _latest(state)["n"]) == "needs_decision":
        verbs += f" · {fid} fix (moves it to Agent can fix)"
    lines.append(f"Mark: {verbs}")
    return "\n".join(lines) + "\n"


def report_findings(state: dict) -> list[dict]:
    """Return the shown findings in report order as `ReportFindings` chunks (RPT-8).

    Returns:
        Dicts `{"level": ..., "findings": [...]}` of at most 32 findings each; empty when
        nothing is shown.
    """
    level = _latest(state)["level"]
    records = [
        {
            "file": f["anchor"]["path"],
            **({"line": f["anchor"]["line"]} if f["anchor"]["line"] else {}),
            "summary": f["claim"],
            "failure_scenario": f["trigger"] or f["claim"],
            "category": f["category"],
            "short_summary": (f["class"] or f["claim"])[:_CLASS_SHORT],
            "verdict": "PLAUSIBLE" if f["verdict"] == "uncertain" else "CONFIRMED",
        }
        for f in _layout(state).shown()
    ]
    return [
        {"level": level, "findings": records[i : i + _CHUNK]}
        for i in range(0, len(records), _CHUNK)
    ]
