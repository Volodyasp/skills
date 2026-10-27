"""Argument parsing and dispatch for review-cycle-state."""

from __future__ import annotations

import argparse
import re
import sys
import traceback
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from review_cycle.levels import LEVELS

_FID = re.compile(r"F([1-9][0-9]*)")
_TARGET_NAME = re.compile(r"[a-z0-9][a-z0-9.-]*")
_MARK_VERBS = ("intentional", "wontfix", "wrong", "superseded", "open", "fix")
_MODEL_ALIAS = re.compile(r"[A-Za-z0-9._\[\]-]{1,64}")
_NAME = re.compile(r"(?!-)(?!.*\.\.)[A-Za-z0-9._/-]{1,200}")
_PR = re.compile(r"#?([0-9]+)")
_FOCUS_MAX = 500
_MAX_PATHS = 10

TargetKind = Literal["document", "range", "pr", "branch"]


class UsageError(Exception):
    """Invalid user tokens; `main` maps it to exit code 2."""


@dataclass(frozen=True)
class PlanReq:
    """Parsed plan request (CLI-4).

    `target_kind` is None when no target was given (current branch, code mode); `right` is the
    right-hand side of a range target.
    """

    level: str | None
    full: bool
    fresh: bool
    model: str | None
    intent: str | None
    target_kind: TargetKind | None
    target: str | None
    right: str | None = None
    incremental: bool = False
    focus: str | None = None
    paths: tuple[str, ...] = ()


@dataclass(frozen=True)
class MarkReq:
    """Parsed mark request (CLI-2); `fid` is e.g. "F3"; `reason` is None when absent.

    `target` is the state-dir name from a qualified `<target>/F<n>` id (RPT-20(d)), or None
    for a bare id.
    """

    fid: str
    verb: str
    reason: str | None
    target: str | None = None


@dataclass(frozen=True)
class ShowReq:
    """Parsed show request (CLI-3); `fid` is e.g. "F3"; `target` as `MarkReq`'s (RPT-20(d))."""

    fid: str
    target: str | None = None


def _split_qualified_fid(token: str) -> tuple[str | None, str] | None:
    """Return (target, "F<n>") for a bare or `<target>/F<n>` finding id (CLI-2/3, RPT-20(d)).

    Returns:
        None when `token` has no trailing `F<n>` part at all (not a finding id).

    Raises:
        UsageError: `token` ends in `/F<n>` but the target part is not a valid state-dir name
            (lowercase `[a-z0-9][a-z0-9.-]*`, no `..`).
    """
    if "/" not in token:
        return (None, token) if _FID.fullmatch(token) else None
    target, _, fid = token.rpartition("/")
    if not _FID.fullmatch(fid):
        return None
    if not _TARGET_NAME.fullmatch(target) or ".." in target:
        raise UsageError(f"invalid finding id {token!r}")
    return target, fid


def _parse_mark(tokens: list[str], target: str | None, fid: str) -> MarkReq:
    verb, *rest = tokens
    if verb not in _MARK_VERBS:
        raise UsageError(f"unknown verb {verb!r}; use one of {', '.join(_MARK_VERBS)}")
    reason = " ".join(rest) if rest else None
    if verb == "wrong" and not (reason or "").strip():
        raise UsageError("mark wrong needs a reason")
    return MarkReq(fid, verb, reason, target)


def _parse_show(tokens: list[str]) -> ShowReq:
    if len(tokens) == 1:
        raise UsageError("add a verb, or use show F<n>")
    split = _split_qualified_fid(tokens[1]) if len(tokens) == 2 else None
    if split is None:
        raise UsageError("usage: show F<n>")
    target, fid = split
    return ShowReq(fid, target)


def _check_name(name: str) -> str:
    if not _NAME.fullmatch(name):
        raise UsageError(f"invalid target {name!r}")
    return name


def _classify_target(
    token: str,
) -> tuple[TargetKind, str, str | None]:
    """Return (kind, target, right) for a plan target token (CLI-4 order)."""
    if token.endswith(".md"):
        return "document", token, None
    if "..." in token:
        ref, _, right = token.partition("...")
        return "range", _check_name(ref), _check_name(right) if right else None
    pr = _PR.fullmatch(token)
    if pr:
        return "pr", pr.group(1), None
    return "branch", _check_name(token), None


def _parse_plan(tokens: list[str]) -> PlanReq:
    level: str | None = None
    full = fresh = incremental = False
    model: str | None = None
    intent: str | None = None
    focus: str | None = None
    paths: list[str] = []
    target: tuple[TargetKind, str, str | None] | None = None
    it = iter(tokens)
    for arg in it:
        if arg == "--full":
            full = True
        elif arg == "--fresh":
            fresh = True
        elif arg == "--incremental":
            incremental = True
        elif arg == "--path":
            value = next(it, None)
            if value is None:
                raise UsageError(f"{arg} needs a value")
            if not value or value.startswith("-"):
                raise UsageError(f"invalid --path {value!r}")
            paths.append(value)
        elif arg == "--focus":
            value = next(it, None)
            if value is None:
                raise UsageError(f"{arg} needs a value")
            if focus is not None:
                raise UsageError("--focus given more than once")
            stripped = value.strip()
            if not stripped:
                raise UsageError("--focus needs text")
            if len(stripped) > _FOCUS_MAX:
                raise UsageError(f"--focus is longer than {_FOCUS_MAX} characters")
            focus = stripped
        elif arg in ("--model", "--intent"):
            value = next(it, None)
            if value is None:
                raise UsageError(f"{arg} needs a value")
            if (intent if arg == "--intent" else model) is not None:
                raise UsageError(f"{arg} given more than once")
            if arg == "--intent":
                intent = value
            elif _MODEL_ALIAS.fullmatch(value):
                model = value
            else:
                raise UsageError(f"invalid model alias {value!r}")
        elif arg.startswith("--"):
            raise UsageError(f"unknown flag {arg}")
        elif arg in LEVELS:
            if level is not None:
                raise UsageError("more than one level given")
            level = arg
        elif target is not None:
            raise UsageError("more than one target given")
        else:
            target = _classify_target(arg)
    if incremental and (full or fresh):
        raise UsageError("--incremental conflicts with --full/--fresh")
    if len(paths) > _MAX_PATHS:
        raise UsageError(f"at most {_MAX_PATHS} --path flags")
    kind, name, right = target if target else (None, None, None)
    if paths and kind == "document":
        raise UsageError("--path works only in code mode")
    return PlanReq(
        level, full, fresh, model, intent, kind, name, right, incremental, focus, tuple(paths)
    )


def parse_tokens(tokens: list[str]) -> PlanReq | MarkReq | ShowReq:
    """Classify user tokens as a plan, mark or show request.

    Raises:
        UsageError: unknown flag, bad alias, two targets, invalid target, or `wrong` without a
            reason.
    """
    if tokens and tokens[0] == "show":
        return _parse_show(tokens)
    if tokens:
        split = _split_qualified_fid(tokens[0])
        if split is not None:
            if len(tokens) == 1:
                raise UsageError("add a verb, or use show F<n>")
            target, fid = split
            return _parse_mark(tokens[1:], target, fid)
    return _parse_plan(tokens)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="review-cycle-state")
    sub = parser.add_subparsers(dest="command", required=True)
    cli_p = sub.add_parser("cli", help="plan a round, or mark/show a finding")
    cli_p.add_argument("--data-dir", default="")
    cli_p.add_argument("tokens", nargs=argparse.REMAINDER)
    cont_p = sub.add_parser("continue", help="confirm a plan awaiting confirmation")
    cont_p.add_argument("--data-dir", default="")
    cont_p.add_argument("--state-dir", required=True)
    merge_p = sub.add_parser("merge", help="merge a workflow result into the state")
    merge_p.add_argument("--data-dir", default="")
    merge_p.add_argument("--state-dir", required=True)
    merge_p.add_argument("--result", required=True)
    return parser


def _split_cli_args(args: list[str]) -> tuple[str, list[str]]:
    """Split `cli` arguments into (`--data-dir` value, user tokens); the flag comes first."""
    if args and args[0] == "--data-dir":
        return (args[1] if len(args) > 1 else ""), args[2:]
    if args and args[0].startswith("--data-dir="):
        return args[0].partition("=")[2], args[1:]
    return "", args


def _scan_data_dir(args: list[str]) -> str:
    """Return the `--data-dir` value of `continue`/`merge` arguments ("" when absent).

    Read before argparse so that CLI-13 wins over other argument errors.
    """
    for i, arg in enumerate(args):
        if arg == "--data-dir":
            return args[i + 1] if i + 1 < len(args) else ""
        if arg.startswith("--data-dir="):
            return arg.partition("=")[2]
    return ""


def _data_dir_error(text: str) -> str | None:
    if not text or "${" in text:
        return "--data-dir not set (plugin data dir)"
    if not Path(text).is_absolute():
        return "--data-dir must be an absolute path"
    return None


def _refuse(code: int, message: str) -> int:
    print(f"next: stop\nerror: {message}")
    print(f"error: {message}", file=sys.stderr)
    return code


def _dispatch(command: str, data_dir: Path, tokens: list[str], ns: argparse.Namespace) -> int:
    # Imported here: `commands` imports the request types from this module.
    from review_cycle import commands

    if command == "continue":
        return commands.cont(data_dir, Path(ns.state_dir))
    if command == "merge":
        return commands.merge(data_dir, Path(ns.state_dir), Path(ns.result))
    req = parse_tokens(tokens)
    if isinstance(req, MarkReq):
        return commands.mark(req, data_dir, Path.cwd())
    if isinstance(req, ShowReq):
        return commands.show(req, data_dir, Path.cwd())
    return commands.plan(req, data_dir, Path.cwd())


def main(argv: list[str]) -> int:
    """Run `cli`, `continue` or `merge` and return the exit code (CLI-1, CLI-10).

    Prints the CLI-9 contract on stdout. Unexpected exceptions become exit 1
    `error: internal: <type>: <msg>`.
    """
    tokens: list[str] = []
    ns = argparse.Namespace()
    command = argv[0] if argv else ""
    if command not in ("cli", "continue", "merge") or argv[1:2] in (["-h"], ["--help"]):
        _build_parser().parse_args(argv)  # prints help or the usage error, then exits
        return 2
    if command == "cli":
        data_dir_text, tokens = _split_cli_args(argv[1:])
    else:
        data_dir_text = _scan_data_dir(argv[1:])
    error = _data_dir_error(data_dir_text)
    if error:
        return _refuse(3, error)
    if command != "cli":
        ns = _build_parser().parse_args(argv)
    try:
        return _dispatch(command, Path(data_dir_text), tokens, ns)
    except UsageError as exc:
        return _refuse(2, str(exc))
    except Exception as exc:  # noqa: BLE001 - last-resort mapping to exit 1 (SPECS §12)
        traceback.print_exc()
        return _refuse(1, f"internal: {type(exc).__name__}: {exc}")
