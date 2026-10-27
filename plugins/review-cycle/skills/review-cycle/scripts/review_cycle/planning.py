"""Plan content (ST-1): scope, small-diff cut, no-repeat and re-check lists, intent, workflow args."""

from __future__ import annotations

import json
import re
import shlex
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from review_cycle import docmode, gitio, rounds, store
from review_cycle import findings as fnd
from review_cycle.cli import PlanReq
from review_cycle.levels import SMALL_DIFF_MAX_FILES, SMALL_DIFF_MAX_LINES, level_config
from review_cycle.snapshot import Snapshot, read_current

WORKFLOW_NAME = "review-cycle:round"
VERIFIER_SECTION = "## Verifier"
_RULES_FILES = ("CLAUDE.md", "AGENTS.md", ".claude/CLAUDE.md")
_LOCK_NAMES = frozenset({"package-lock.json", "pnpm-lock.yaml", "go.sum"})
_LINKED_DOC = re.compile(r"[\w./-]+\.md")
_REFERENCES_DIR = Path(__file__).resolve().parents[2] / "references"
_LEVEL_PRIORITY = ("high", "medium", "low", "xhigh", "max")
_SCOPE_WORDS = ("incremental", "full", "fresh")
_SCOPE_FLAG = {"incremental": "--incremental", "full": "--full"}


def _is_lock_file(path: str) -> bool:
    name = path.rsplit("/", 1)[-1]
    return name.endswith(".lock") or name in _LOCK_NAMES


def _diff_cmd(repo: Path, snap: Snapshot, files: list[str]) -> str:
    """Return the shell command that prints the branch's own diff of `files` (RND-10).

    It names the repository with `-C`, so it works from any directory.
    """
    if snap.base is None or not files:
        # No file diff to show: an empty `-- ` pathspec would print the whole branch.
        return "true"
    words = ["git", "-C", str(repo), "-c", "core.quotepath=false", "diff", "--no-ext-diff"]
    words += ["--no-textconv", snap.base.merge_base, snap.tree_sha or "", "--", *files]
    return " ".join(shlex.quote(word) for word in words)


def _doc_section_keys(snap: Snapshot, state: dict | None, wide: bool) -> list[str]:
    """Return the section keys in scope: every section when `wide`, else changed or new ones."""
    sections = docmode.section_hashes(snap.doc_text or "")
    if wide:
        return list(sections)
    return docmode.changed_sections((state or {}).get("sections", {}), sections)


def _doc_scope_lines(snap: Snapshot, keys: list[str]) -> int:
    bodies = docmode.sections(snap.doc_text or "")
    return sum(len(bodies[k].splitlines()) for k in keys)


def _code_counted(snap: Snapshot, files: list[str]) -> tuple[list[str], int]:
    """Return (files, lines) counted toward the small-diff rule (RND-13) and its agent estimate
    (RND-15): lock/generated files never count toward either."""
    counted = [f for f in files if not _is_lock_file(f)]
    return counted, sum(snap.line_counts.get(f, 0) for f in counted)


def _scope(
    repo: Path,
    snap: Snapshot,
    state: dict | None,
    n: int,
    full: bool,
    incremental: bool,
    base_changed: bool,
) -> dict:
    """Build the plan's `scope` (ST-1, RPT-18)."""
    if snap.mode == "document":
        wide = n == 1 or full or not incremental
        keys = _doc_section_keys(snap, state, wide)
        return {
            "kind": "full" if wide else "since",
            "files": [snap.doc_rel],
            "deleted": [],
            "sections": keys,
            "lines": _doc_scope_lines(snap, keys),
            "diff_cmd": "true",
            "since_round": None if wide else (state or {}).get("round"),
            "base_changed_from": None,
        }
    prev_ids = state.get("file_ids") if state else None
    decided = rounds.decide_scope(n, full, incremental, base_changed, prev_ids, snap.file_ids)
    kind = decided["kind"]
    return {
        "kind": kind,
        "files": decided["files"],
        "deleted": decided["deleted"],
        "sections": [],
        "lines": sum(snap.line_counts.get(f, 0) for f in decided["files"]),
        "diff_cmd": _diff_cmd(repo, snap, decided["files"]),
        "since_round": state["round"] if state and kind == "since" else None,
        "base_changed_from": state["base_ref"] if state and base_changed else None,
    }


def _scope_counts(snap: Snapshot, state: dict | None, n: int, incremental: bool) -> tuple[int, int]:
    """Return (item count, lines) of the scope `incremental` would give at round `n`.

    Item count is files (code) or sections (document). Uses the same lock-file exclusion as
    `_small_diff` (RND-13), so a choose-step estimate matches the plan it describes. Used only
    to size choose-step estimates, never written to a plan.
    """
    if snap.mode == "document":
        keys = _doc_section_keys(snap, state, wide=not incremental)
        return len(keys), _doc_scope_lines(snap, keys)
    prev_ids = state.get("file_ids") if state else None
    decided = rounds.decide_scope(n, not incremental, incremental, False, prev_ids, snap.file_ids)
    counted, lines = _code_counted(snap, decided["files"])
    return len(counted), lines


def _small_diff(snap: Snapshot, scope: dict, level: str, model: str | None) -> tuple[dict, dict]:
    """Return (level_config, small_diff record) for the round (RND-13)."""
    full_cfg = level_config(level, snap.mode, model, False)
    counted, lines = _code_counted(snap, scope["files"])
    cut = snap.mode == "code" and rounds.is_small(lines, len(counted))
    cfg = level_config(level, snap.mode, model, cut)
    before, after = len(full_cfg["finders"]), len(cfg["finders"])
    record = {
        "applied": cut and after < before,
        "lines": lines if snap.mode == "code" else scope["lines"],
        "files": len(counted) if snap.mode == "code" else 1,
        "max_lines": SMALL_DIFF_MAX_LINES,
        "max_files": SMALL_DIFF_MAX_FILES,
        "finders_from": before,
        "finders_to": after,
    }
    return cfg, record


def _known_list(repo: Path, snap: Snapshot, state: dict | None) -> list[dict]:
    """Return the no-repeat list (RND-11)."""
    if not state:
        return []
    keys = ("category", "class", "path", "symbol", "claim")
    known = [
        {
            "id": f["id"],
            "category": f["category"],
            "class": f["class"],
            "path": f["anchor"]["path"],
            "symbol": f["anchor"]["symbol"],
            "claim": f["claim"],
            "status": f["status"],
        }
        for f in state["findings"]
        if f["status"] != "fixed"
    ]
    texts: dict[str, str | None] = {}
    for entry in state["rejected"]:
        path = entry["path"]
        if path not in texts:
            texts[path] = read_current(repo, snap, path)
        if fnd.snippet_present(texts[path], entry["snippet_hash"], entry["snippet_lines"]):
            known.append({"id": "-", **{k: entry[k] for k in keys}, "status": "rejected"})
    return known


def _recheck_list(state: dict | None) -> list[dict]:
    """Return the open findings to re-verify (RND-12), with the verifier-readable fields."""
    if not state:
        return []
    return [
        {
            "id": f["id"],
            "path": f["anchor"]["path"],
            "line": f["anchor"]["line"],
            "symbol": f["anchor"]["symbol"],
            "snippet": f["anchor"]["snippet"],
            "claim": f["claim"],
        }
        for f in state["findings"]
        if f["status"] == "open"
    ]


# ---------------------------------------------------------------- plan: intent and references


def _flag_intent(value: str, repo: Path, cwd: Path) -> tuple[str, str]:
    """Return (ref, text) of an `--intent` value: a file (CLI-6) or literal text."""
    for base in (cwd, repo):
        candidate = base / value
        try:
            if not candidate.is_file():
                continue
            text = candidate.read_text(encoding="utf-8", errors="replace")
            resolved = candidate.resolve()
        except (OSError, ValueError):
            continue
        try:
            return resolved.relative_to(repo.resolve()).as_posix(), text
        except ValueError:
            return str(candidate), text
    return "text", value


def _linked_docs(repo: Path, *texts: str) -> list[str]:
    linked: list[str] = []
    for text in texts:
        for token in _LINKED_DOC.findall(text):
            path = token.removeprefix("./")
            if path.startswith("/") or ".." in path.split("/") or path in linked:
                continue
            if gitio.tracked_at_head(repo, path):
                linked.append(path)
    return linked


def _intent(req: PlanReq, repo: Path, cwd: Path, snap: Snapshot, verify: Path) -> dict:
    """Collect the stated intent into `verify/intent.md` and return the plan's `intent` (RND-16)."""
    sources: list[dict] = []
    sections: list[str] = []
    pr_body = commits = ""
    if snap.base is not None:
        pr = snap.base.pr
        if pr is not None and (pr.get("body") or "").strip():
            pr_body = pr["body"]
            sources.append({"kind": "pr", "ref": f"#{pr['number']}"})
            sections.append(f"## PR #{pr['number']}\n\n{pr_body.strip()}")
        commits = gitio.commit_messages(repo, snap.base.merge_base)
        if commits.strip():
            ref = f"{snap.base.merge_base[:7]}..{snap.head_sha[:7]}"
            sources.append({"kind": "commit", "ref": ref})
            sections.append(f"## Commits\n\n{commits.strip()}")
    if req.intent is not None:
        ref, text = _flag_intent(req.intent, repo, cwd)
        sources.append({"kind": "flag", "ref": ref})
        sections.append(f"## --intent\n\n{text.strip()}")
    if snap.mode == "code":
        linked = _linked_docs(repo, pr_body, commits)
        sources += [{"kind": "linked", "ref": path} for path in linked]
        if linked:
            sections.append("## Linked\n\n" + "\n".join(f"- {path}" for path in linked))
    intent_file = verify / "intent.md"
    store.write_text(intent_file, "\n\n".join(sections) + ("\n" if sections else ""))
    stated = any(s["kind"] in ("pr", "flag", "linked") for s in sources)
    return {"file": str(intent_file), "sources": sources, "none": not stated}


def _review_md(repo: Path, snap: Snapshot, verify: Path) -> dict:
    """Copy REVIEW.md from the merge-base into `verify/` (RND-17); the branch's copy is ignored."""
    copy = verify / "review-md-base.md"
    text = gitio.show(repo, snap.base.merge_base, "REVIEW.md") if snap.base else None
    if text is None:
        copy.unlink(missing_ok=True)
        return {"path": None, "nit_cap": fnd.nit_cap(None)}
    store.write_text(copy, text)
    return {"path": str(copy), "nit_cap": fnd.nit_cap(text)}


def _workflow_args(plan: dict, req: PlanReq) -> dict:
    cfg = plan["level_config"]
    return {
        "v": 1,
        "plan_id": plan["plan_id"],
        "plan": str(Path(plan["state_dir"]) / "plan.json"),
        "repo_root": plan["repo_root"],
        "mode": plan["mode"],
        "level": plan["level"],
        "finders": cfg["finders"],
        "finder_model": cfg["finder_model"],
        "votes": cfg["votes"],
        "tiebreak": cfg["tiebreak"],
        "sweep": cfg["sweep"],
        "model_override": req.model is not None,
        "depth": cfg["depth"],
        "lens_file": plan["references"]["lens_file"],
        "verifier_section": VERIFIER_SECTION,
        "verify_dir": plan["verify_dir"],
        "state_dir": plan["state_dir"],
        "intent_file": plan["intent"]["file"],
        "review_md": plan["review_md"]["path"],
        "rules_files": plan["rules_files"],
        "recheck_file": plan["recheck_file"],
        "recheck": plan["recheck"],
        "focus": plan["focus"],
        "paths": plan["paths"] or None,
    }


def _level_recommendation(state: dict | None, data_dir: Path) -> tuple[str, str]:
    """Return (level, reason) recommended when no level is typed (RPT-18)."""
    if state and state["rounds"]:
        return state["rounds"][-1]["level"], "last round's level"
    remembered = store.last_level(data_dir)
    return (remembered, "last used level") if remembered else ("high", "default")


def _scope_recommendation(
    mode: str, n: int, state: dict, base_ref: str | None, effective_level: str
) -> tuple[str, str]:
    """Return (scope word, reason) recommended for round `n` >= 2 (RPT-18)."""
    if state.get("base_ref") not in (None, base_ref):
        return "full", f"base changed: {state['base_ref']} → {base_ref}"
    ids_field = "file_ids" if mode == "code" else "sections"
    if state.get(ids_field) is None:
        return "full", "no saved file ids"
    if rounds.level_rank(effective_level) > rounds.max_earlier_rank(state["rounds"]):
        return "full", "level raised above earlier rounds"
    return "incremental", f"only changes since round {n - 1}"


def _level_options(
    snap: Snapshot,
    state: dict | None,
    n: int,
    scope_word: str,
    rec_level: str,
    rec_reason: str,
    recheck_n: int,
    model: str | None,
) -> list[tuple[str, str]]:
    """Level choices for the choose step: recommended first, then 3 more (RPT-18)."""
    items, lines = _scope_counts(snap, state, n, scope_word == "incremental")
    words = [rec_level, *[w for w in _LEVEL_PRIORITY if w != rec_level][:3]]
    options: list[tuple[str, str]] = []
    for word in words:
        total = rounds.estimate_total(word, snap.mode, model, lines, items, recheck_n)
        text = f"~{total} agents"
        if word == rec_level:
            text = f"recommended ({rec_reason}) · {text}"
        options.append((word, text))
    return options


def _scope_options(
    snap: Snapshot,
    state: dict | None,
    n: int,
    effective_level: str,
    model: str | None,
    recheck_n: int,
    rec_word: str,
    rec_reason: str,
) -> list[tuple[str, str]]:
    """Scope choices for the choose step: recommended first, then the other two (RPT-18)."""
    noun = "section" if snap.mode == "document" else "file"
    target = "document" if snap.mode == "document" else "branch"
    inc_items, inc_lines = _scope_counts(snap, state, n, True)
    full_items, full_lines = _scope_counts(snap, state, n, False)
    inc_total = rounds.estimate_total(
        effective_level, snap.mode, model, inc_lines, inc_items, recheck_n
    )
    full_total = rounds.estimate_total(
        effective_level, snap.mode, model, full_lines, full_items, recheck_n
    )
    # `fresh` forgets every finding, so its estimate has no re-check agents, unlike `full`'s.
    fresh_total = rounds.estimate_total(
        effective_level, snap.mode, model, full_lines, full_items, 0
    )
    descriptions = {
        "incremental": (
            f"{rounds.count_noun(inc_items, noun)} changed since round {n - 1} · "
            f"re-check of {rounds.count_noun(recheck_n, 'open finding')} · ~{inc_total} agents"
        ),
        "full": f"whole {target}: {rounds.count_noun(full_items, noun)} · ~{full_total} agents",
        "fresh": f"forget all findings and start again at round 1 · ~{fresh_total} agents",
    }
    words = [rec_word, *(w for w in _SCOPE_WORDS if w != rec_word)]
    options: list[tuple[str, str]] = []
    for word in words:
        text = descriptions[word]
        if word == rec_word:
            text = f"recommended ({rec_reason}) · {text}"
        options.append((word, text))
    return options


@dataclass(frozen=True)
class Choice:
    """What the choose step (RPT-18) must ask before a round can be planned."""

    round_n: int
    mode: str
    ask_level: bool
    ask_scope: bool
    level_options: list[tuple[str, str]]
    scope_options: list[tuple[str, str]]
    recommended_tokens: list[str]


def build_choice(
    req: PlanReq, data_dir: Path, snap: Snapshot, state: dict | None, forced: bool
) -> Choice | None:
    """Return what to ask before `assemble_plan`, or None when level and scope are both settled.

    Returns:
        None when `req.level` is typed and the scope is already resolved (round 1, `--full`,
        `--fresh`, a forced rerun, or `--incremental`); writes nothing either way.
    """
    n = state["round"] + 1 if state else 1
    ask_level = req.level is None
    ask_scope = n >= 2 and not forced and not req.full and not req.incremental
    if not ask_level and not ask_scope:
        return None
    rec_level, level_reason = _level_recommendation(state, data_dir)
    effective_level = req.level if req.level is not None else rec_level
    recheck_n = len(_recheck_list(state))
    rec_scope_word = "full"
    rec_scope_reason = ""
    if n >= 2:
        base_ref = snap.base.ref if snap.base else None
        rec_scope_word, rec_scope_reason = _scope_recommendation(
            snap.mode, n, state or {}, base_ref, effective_level
        )
    if n == 1 or req.full or forced:
        effective_scope_word = "full"
    elif req.incremental:
        effective_scope_word = "incremental"
    else:
        effective_scope_word = rec_scope_word
    recommended_tokens: list[str] = []
    level_options: list[tuple[str, str]] = []
    scope_options: list[tuple[str, str]] = []
    if ask_level:
        level_options = _level_options(
            snap, state, n, effective_scope_word, rec_level, level_reason, recheck_n, req.model
        )
        recommended_tokens.append(rec_level)
    if ask_scope:
        scope_options = _scope_options(
            snap,
            state,
            n,
            effective_level,
            req.model,
            recheck_n,
            rec_scope_word,
            rec_scope_reason,
        )
        recommended_tokens.append(_SCOPE_FLAG[rec_scope_word])
    return Choice(
        n, snap.mode, ask_level, ask_scope, level_options, scope_options, recommended_tokens
    )


def _prepare_state_dir(sd: Path) -> Path:
    gitignore = sd / ".gitignore"
    if not gitignore.exists():
        store.write_text(gitignore, "*\n")
    verify = store.verify_dir(sd)
    verify.mkdir(parents=True, exist_ok=True)
    return verify


@dataclass
class Run:
    """Where a plan runs: repository, caller's directory, branch and the two data locations."""

    repo: Path
    cwd: Path
    branch: str
    data_dir: Path
    state_dir: Path


def _warning(mode: str, level: str, scope: dict, state: dict | None) -> str | None:
    """Return the RPT-18 `since`-scope warning line text, or None when it does not apply."""
    if scope["kind"] != "since" or not state:
        return None
    if rounds.level_rank(level) <= rounds.max_earlier_rank(state["rounds"]):
        return None
    noun = "sections" if mode == "document" else "files"
    return (
        f"level raised to {level}; {noun} outside this round were not reviewed at it (use --full)"
    )


def assemble_plan(req: PlanReq, run: Run, snap: Snapshot, state: dict | None, forced: bool) -> dict:
    """Build `plan.json` content (ST-1) for the next round.

    Pre-condition: `req.level` is typed and the scope is resolved (round 1, `--full`, `--fresh`,
    a forced rerun, or `--incremental`) — guaranteed by `build_choice` returning None first.
    """
    if req.level is None:
        raise RuntimeError("internal: assemble_plan called without a typed level")
    n = state["round"] + 1 if state else 1
    verify = _prepare_state_dir(run.state_dir)
    level, level_source = req.level, "typed"
    base_ref = snap.base.ref if snap.base else None
    base_changed = state is not None and state.get("base_ref") not in (None, base_ref)
    scope = _scope(
        run.repo, snap, state, n, req.full or forced, bool(req.incremental), base_changed
    )
    cfg, small = _small_diff(snap, scope, level, req.model)
    recheck = _recheck_list(state)
    recheck_file = verify / "recheck.json"
    store.write_text(recheck_file, json.dumps(recheck, ensure_ascii=False, indent=2) + "\n")
    rules = [str(run.repo / rel) for rel in _RULES_FILES if (run.repo / rel).is_file()]
    plan: dict[str, Any] = {
        "v": 1,
        "plan_id": uuid.uuid4().hex,
        "created_at": store.utc_now(),
        "status": "ready",
        "repo_root": str(run.repo),
        "state_dir": str(run.state_dir),
        "verify_dir": str(verify),
        "mode": snap.mode,
        "target": snap.target,
        "branch": run.branch,
        "base_ref": base_ref,
        "paths": snap.paths,
        "base_reason": snap.base.reason if snap.base else None,
        "merge_base": snap.base.merge_base if snap.base else None,
        "head_sha": snap.head_sha,
        "tree_sha": snap.tree_sha,
        "doc_sha256": snap.doc_sha256,
        "change_id": snap.change_id,
        "file_ids": snap.file_ids,
        "round": n,
        "level": level,
        "level_source": level_source,
        "model_override": req.model,
        "level_config": cfg,
        "small_diff": small,
        "scope": scope,
        "warning": _warning(snap.mode, level, scope, state),
        "focus": req.focus,
        "known": _known_list(run.repo, snap, state),
        "recheck_file": str(recheck_file),
        "recheck": [{"id": r["id"], "path": r["path"]} for r in recheck],
        "review_md": _review_md(run.repo, snap, verify),
        "rules_files": rules,
        "intent": _intent(req, run.repo, run.cwd, snap, verify),
        "references": {
            "lens_file": str(
                _REFERENCES_DIR / ("code.md" if snap.mode == "code" else "document.md")
            ),
            "verifier_section": VERIFIER_SECTION,
        },
        "agents_estimate": rounds.agent_estimate(cfg, len(recheck)),
    }
    plan["workflow"] = {"name": WORKFLOW_NAME, "args": _workflow_args(plan, req)}
    return plan
