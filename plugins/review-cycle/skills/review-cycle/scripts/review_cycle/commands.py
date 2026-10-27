"""CLI subcommand implementations. Each returns the process exit code (CLI-10)."""

from __future__ import annotations

import hashlib
import json
import shlex
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

from review_cycle import diffs, docmode, gitio, rounds, store
from review_cycle import findings as fnd
from review_cycle.cli import MarkReq, PlanReq, ShowReq
from review_cycle.planning import WORKFLOW_NAME, Choice, Run, assemble_plan, build_choice
from review_cycle.report import render_report, render_round_md, render_show, report_findings
from review_cycle.result import ResultError, unwrap, validate
from review_cycle.snapshot import Stop, code_snapshot, decode_document, doc_snapshot

_REPORT_OPEN = "=== report ==="
_REPORT_CLOSE = "=== end report ==="


def _guarded(command: Callable[..., int]) -> Callable[..., int]:
    """Turn a refusal or a failed git call raised by `command` into CLI-9 error output."""

    def fail(code: int, message: str) -> int:
        print(f"next: stop\nerror: {message}")
        print(f"error: {message}", file=sys.stderr)
        return code

    def run(*args: Any) -> int:
        try:
            return command(*args)
        except Stop as stop:
            return fail(stop.code, stop.message)
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
            return fail(1, gitio.describe_failure(exc))

    return run


def _print_fenced(text: str) -> None:
    print(f"{_REPORT_OPEN}\n{text.rstrip(chr(10))}\n{_REPORT_CLOSE}")


def _error_text(exc: ResultError) -> str:
    return str(exc).removeprefix("error: ")


def _load_json(path: Path) -> dict | None:
    """Read a JSON object file; a corrupt file is a refusal that names it."""
    try:
        loaded = store.read_json(path)
    except ValueError as exc:
        raise Stop(1, f"{path} is not valid JSON: {exc}") from None
    if loaded is not None and not isinstance(loaded, dict):
        raise Stop(1, f"{path} is not a JSON object")
    return loaded


def _ensure_data_dir(data_dir: Path) -> None:
    try:
        data_dir.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise Stop(3, f"--data-dir not usable: {exc}") from None


# ---------------------------------------------------------------- repository context


def _repo_of(cwd: Path) -> Path:
    try:
        return gitio.toplevel(cwd)
    except FileNotFoundError:
        raise Stop(3, "git not found") from None
    except subprocess.CalledProcessError:
        raise Stop(3, "not a git repository") from None


def _branch_of(repo: Path) -> str:
    branch = gitio.current_branch(repo)
    if branch is None:
        raise Stop(1, "detached HEAD; check out a branch")
    return branch


def _repo_id(repo: Path) -> str:
    """Return the repository identity written to `outcomes.jsonl` (ST-7)."""
    url = gitio.origin_url(repo)
    return store.strip_userinfo(url) if url else str(repo)


def _state_dir_of(repo: Path, branch: str, target: str) -> Path:
    try:
        return store.state_dir(repo, branch, target)
    except ValueError as exc:
        raise Stop(1, str(exc)) from None


# ---------------------------------------------------------------- plan


_count = rounds.count_noun


def _print_new_round(plan: dict) -> None:
    scope, est, small = plan["scope"], plan["agents_estimate"], plan["small_diff"]
    kinds = {
        "full": "full",
        "since": f"since round {scope['since_round']}",
        "full_fallback": "full (no previous file ids)",
        "full_base_changed": "full (base changed)",
    }
    size = (
        _count(len(scope["sections"]), "section")
        if plan["mode"] == "document"
        else f"{_count(len(scope['files']), 'file')} · {_count(scope['lines'], 'line')}"
    )
    print(f"state: {plan['state_dir']}")
    print(
        f"round: {plan['round']} · {plan['mode']} · {plan['level']} · {kinds[scope['kind']]} · {size}"
    )
    if plan["mode"] == "code":
        print(f"base: {plan['base_ref']} ({plan['base_reason']})")
    if plan["paths"]:
        print(f"paths: {', '.join(plan['paths'])}")
    if scope["base_changed_from"]:
        suffix = "; full scope" if scope["kind"] == "full_base_changed" else ""
        print(f"base changed: {scope['base_changed_from']} → {plan['base_ref']}{suffix}")
    if plan["warning"]:
        print(f"warning: {plan['warning']}")
    sweep = f" + sweep ≤ {est['sweep']}" if plan["level_config"]["sweep"] else ""
    print(
        f"agents: ~{est['total']} (finders {est['finders']} + verifiers {est['verifiers']}"
        f" + tie-break ≤ {est['tiebreak']}{sweep})"
    )
    if small["applied"]:
        print(f"small-diff: {small['finders_from']} → {small['finders_to']} finders")
    if plan["focus"]:
        print(f"focus: {plan['focus']}")
    if plan["intent"]["none"]:
        print("intent: none")
    print(f"next: workflow\nworkflow-name: {WORKFLOW_NAME}")
    print(f"workflow-args: {json.dumps(plan['workflow']['args'])}")


def _print_question(plan: dict, data_dir: Path, ids: list[str]) -> None:
    state_dir = plan["state_dir"]
    print(f"state: {state_dir}\nnext: ask")
    print(
        f"question: Open Important findings survived a fix round ({', '.join(ids)}). "
        "Reconsider the approach?"
    )
    print("options: reconsider | continue")
    print(
        "on-continue: review-cycle-state continue "
        f"--data-dir {shlex.quote(str(data_dir))} --state-dir {shlex.quote(state_dir)}"
    )


def _print_choice(choice: Choice) -> None:
    """Print the RPT-18 choose lines; the caller writes nothing (no plan, no state change)."""
    print("next: choose")
    print(f"round: {choice.round_n} · {choice.mode}")
    if choice.ask_level:
        print(f"question-level: Review level for round {choice.round_n}?")
        for word, desc in choice.level_options:
            print(f"option-level: {word} | {desc}")
    if choice.ask_scope:
        target = "document" if choice.mode == "document" else "branch"
        print(
            f"question-scope: Round {choice.round_n}: only what changed since round "
            f"{choice.round_n - 1}, or the whole {target}?"
        )
        for word, desc in choice.scope_options:
            print(f"option-scope: {word} | {desc}")
    print(f"recommended: {' '.join(shlex.quote(t) for t in choice.recommended_tokens)}")


def _peek_state(req: PlanReq, sd: Path, branch: str) -> dict | None:
    """Load the state the unchanged and choose checks see; never writes (RND-18).

    `--fresh` is read as having no state yet. Archiving it (RND-8) is deferred to
    `_commit_fresh`, called only once the choose step (RPT-18) is satisfied, so a `--fresh`
    plan that still needs to ask a question leaves the state dir untouched.
    """
    state = _load_json(sd / "state.json")
    if req.fresh:
        return None
    if state is not None and state.get("branch") != branch:
        raise Stop(
            1,
            f"state dir {sd} belongs to branch {state.get('branch')}; "
            f"run with --fresh to start over for {branch}",
        )
    return state


def _commit_fresh(req: PlanReq, sd: Path) -> None:
    """Archive the state dir for `--fresh` (RND-8), now that a round will actually be planned."""
    if req.fresh and ((sd / "state.json").exists() or (sd / "plan.json").exists()):
        store.archive(sd, store.utc_now().replace("-", "").replace(":", ""))


def _print_unchanged(sd: Path, state: dict) -> None:
    print(f"state: {sd}\nnext: print-report")
    _print_fenced(render_report(state, no_change_of=state["round"]))


@_guarded
def plan(req: PlanReq, data_dir: Path, cwd: Path) -> int:
    """Create or reuse the round plan and print the CLI-9 lines for it."""
    _ensure_data_dir(data_dir)
    repo = _repo_of(cwd)
    branch = _branch_of(repo)
    if req.target_kind == "document":
        snap = doc_snapshot(req, repo, cwd)
    else:
        snap = code_snapshot(req, repo, cwd, branch)
    if snap.base is not None and not snap.file_ids:
        under = f"under {', '.join(snap.paths)} " if snap.paths else ""
        print(f"next: stop\nreason: no changes {under}against {snap.base.ref}")
        return 0
    sd = _state_dir_of(repo, branch, snap.target)
    state = _peek_state(req, sd, branch)
    forced = False
    if state is not None and state.get("change_id") == snap.change_id:
        last_level = state["rounds"][-1]["level"] if state["rounds"] else ""
        if not rounds.rerun_unchanged(req.level, last_level, req.full, req.focus):
            _print_unchanged(sd, state)
            return 0
        forced = True
    choice = build_choice(req, data_dir, snap, state, forced)
    if choice is not None:
        _print_choice(choice)
        return 0
    _commit_fresh(req, sd)
    new_plan = assemble_plan(req, Run(repo, cwd, branch, data_dir, sd), snap, state, forced)
    store.set_last_level(data_dir, new_plan["level"])
    ids = [
        f["id"]
        for f in (state or {}).get("findings", [])
        if rounds.reconsider_question(new_plan["round"], [f])
    ]
    if ids:
        new_plan["status"] = "awaiting_confirmation"
    store.write_json(sd / "plan.json", new_plan)
    if ids:
        _print_question(new_plan, data_dir, ids)
    else:
        _print_new_round(new_plan)
    return 0


@_guarded
def cont(data_dir: Path, state_dir: Path) -> int:
    """Confirm a plan awaiting confirmation and print the new-round lines (CLI-11)."""
    stored = _load_json(state_dir / "plan.json")
    if stored is None or stored.get("status") != "awaiting_confirmation":
        raise Stop(1, "no plan is awaiting confirmation")
    stored["status"] = "ready"
    store.write_json(state_dir / "plan.json", stored)
    _print_new_round(stored)
    return 0


# ---------------------------------------------------------------- merge


def _initial_state(plan_: dict) -> dict:
    return {
        "v": 1,
        "mode": plan_["mode"],
        "target": plan_["target"],
        "branch": plan_["branch"],
        "base_ref": plan_["base_ref"],
        "base_sha": plan_["merge_base"],
        "head_sha": plan_["head_sha"],
        "tree_sha": plan_["tree_sha"],
        "change_id": plan_["change_id"],
        "round": 0,
        "last_plan_id": None,
        "file_ids": {},
        "sections": {},
        "rounds": [],
        "findings": [],
        "rejected": [],
        "next_id": 1,
        "suggested_rules": [],
    }


def _read_result(result_path: Path) -> dict:
    try:
        raw = json.loads(result_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise Stop(1, f"result file unreadable: {exc}") from None
    try:
        return unwrap(raw)
    except ResultError as exc:
        raise Stop(1, _error_text(exc)) from None


def _intent_texts(repo: Path, plan_: dict) -> list[str]:
    """Return `intent.md` and the linked files at HEAD for the criterion-2 check (FND-8)."""
    intent = plan_["intent"]
    texts = [Path(intent["file"]).read_text(encoding="utf-8")]
    for source in intent["sources"]:
        if source["kind"] == "linked":
            texts.append(gitio.show(repo, "HEAD", source["ref"]) or "")
    return texts


def _merge_context(
    repo: Path, plan_: dict, state: dict, result: dict
) -> tuple[fnd.MergeContext, str | None]:
    """Gather what `merge_round` needs from the reviewed content; also return the doc text."""
    ctx = fnd.MergeContext(now=store.utc_now(), intent_texts=_intent_texts(repo, plan_))
    paths = {c["path"] for c in result["candidates"]}
    paths |= {f["anchor"]["path"] for f in state["findings"]}
    if plan_["mode"] == "document":
        rel = plan_["scope"]["files"][0]
        raw = (repo / rel).read_bytes()
        if hashlib.sha256(raw).hexdigest() != plan_["doc_sha256"]:
            raise Stop(1, f"{rel} changed since the plan; run /review-cycle again")
        text = decode_document(raw)
        ctx.file_texts = {rel: text}
        ctx.file_ids = docmode.section_hashes(text)
        ctx.doc_path = rel
        return ctx, text
    mb, tree = plan_["merge_base"], plan_["tree_sha"]
    names = gitio.diff_names(repo, mb, tree)
    ctx.file_texts = {p: gitio.show(repo, tree, p) for p in sorted(paths)}
    ctx.ranges = diffs.changed_ranges(gitio.git_diff(repo, mb, tree, unified=0), names)
    ctx.file_ids = dict(plan_["file_ids"])
    return ctx, None


def _new_suggestions(state: dict, outcomes: list[dict], repo_id: str) -> list[str]:
    """Return rule-suggestion texts not yet given, and remember their classes (FND-16)."""
    found = fnd.rule_suggestions(outcomes, repo_id, set(state["suggested_rules"]))
    state["suggested_rules"].extend(s["class"] for s in found)
    return [s["text"] for s in found]


def _print_merged(state: dict) -> None:
    print("next: print-report")
    _print_fenced(render_report(state))
    for chunk in report_findings(state):
        print(f"report-findings: {json.dumps(chunk)}")


@_guarded
def merge(data_dir: Path, state_dir: Path, result_path: Path) -> int:
    """Validate a workflow result, merge it into `state.json`, and print the report (CLI-12)."""
    _ensure_data_dir(data_dir)
    stored = _load_json(state_dir / "plan.json")
    if stored is None:
        raise Stop(1, f"no plan in {state_dir}")
    result = _read_result(result_path)
    state = _load_json(state_dir / "state.json")
    if state is not None and result.get("plan_id") == state.get("last_plan_id"):
        _print_merged(state)
        return 0
    try:
        validate(result, stored)
    except ResultError as exc:
        raise Stop(1, _error_text(exc)) from None
    repo = Path(stored["repo_root"])
    state = state or _initial_state(stored)
    ctx, doc_text = _merge_context(repo, stored, state, result)
    outcome = fnd.merge_round(state, stored, result, ctx)
    repo_id = _repo_id(repo)
    lines = [{**line, "repo": repo_id} for line in outcome.outcome_lines]
    outcome.round_entry["suggestions"] = _new_suggestions(
        state, store.read_outcomes(data_dir) + lines, repo_id
    )
    # Everything is computed; from here on only writes. `state.json` is the commit point and
    # comes after the outcomes: a crash may leave duplicate outcome lines on retry, never lose them.
    store.write_text(state_dir / f"round-{stored['round']}.md", render_round_md(state, outcome))
    if doc_text is not None:
        store.write_text(state_dir / "doc-snapshot.md", doc_text)
    for line in lines:
        store.append_outcome(data_dir, line)
    store.write_json(state_dir / "state.json", state)
    stored["status"] = "merged"
    store.write_json(state_dir / "plan.json", stored)
    _print_merged(state)
    return 0


# ---------------------------------------------------------------- mark and show


def _locate_finding(repo: Path, branch: str, fid: str, target: str | None) -> tuple[Path, dict]:
    """Return (state dir, state) holding finding `fid` (CLI-8; RPT-20(d) qualified ids).

    `target` restricts the search to that one state dir (from a qualified `<target>/F<n>` id);
    None searches every target of `branch`, refusing an id found in more than one.
    """
    parent = _state_dir_of(repo, branch, "code").parent
    if target is not None:
        state = _load_json(parent / target / "state.json") or {}
        if state.get("branch") == branch and any(f["id"] == fid for f in state["findings"]):
            return parent / target, state
        raise Stop(1, f"no finding {target}/{fid}")
    hits: list[tuple[Path, dict]] = []
    for state_json in sorted(parent.glob("*/state.json")):
        state = _load_json(state_json) or {}
        if state.get("branch") == branch and any(f["id"] == fid for f in state["findings"]):
            hits.append((state_json.parent, state))
    if not hits:
        raise Stop(1, f"no finding {fid}")
    if len(hits) > 1:
        names = ", ".join(f"{sd.name}/{fid}" for sd, _ in hits)
        raise Stop(1, f"{fid} exists in several review targets: {names}; repeat with one of them")
    return hits[0]


@_guarded
def mark(req: MarkReq, data_dir: Path, cwd: Path) -> int:
    """Apply a mark verb to a finding of the current branch (FND-15)."""
    _ensure_data_dir(data_dir)
    repo = _repo_of(cwd)
    sd, state = _locate_finding(repo, _branch_of(repo), req.fid, req.target)
    try:
        state, line, message = fnd.apply_mark(state, req.fid, req.verb, req.reason, store.utc_now())
    except ValueError as exc:
        raise Stop(1, str(exc)) from None
    if message != f"{req.fid} {req.verb}":
        print(message)
        return 0
    suggestions: list[str] = []
    if line is not None:
        line = {**line, "repo": _repo_id(repo)}
        if req.verb == "wrong":
            suggestions = _new_suggestions(
                state, store.read_outcomes(data_dir) + [line], line["repo"]
            )
        store.append_outcome(data_dir, line)
    store.write_json(sd / "state.json", state)
    print(f"marked: {message}")
    for text in suggestions:
        print(f"rule-suggestion: {text}")
    return 0


@_guarded
def show(req: ShowReq, data_dir: Path, cwd: Path) -> int:
    """Print the details of a finding (RPT-9)."""
    repo = _repo_of(cwd)
    _, state = _locate_finding(repo, _branch_of(repo), req.fid, req.target)
    print("next: print-report")
    _print_fenced(render_show(state, req.fid))
    return 0
