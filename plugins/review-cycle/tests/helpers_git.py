"""Git and CLI scenario helpers for the S02b tests (conftest.py is S01-owned)."""

from __future__ import annotations

import json
import os
import re
import shlex
import shutil
import subprocess
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest
from conftest import GitRepo
from helpers_result import SEEDED, build_result
from review_cycle.levels import LEVELS

APP = "src/app.py"
UTIL = "src/util.py"
NEW = "src/new.py"
FENCE_OPEN = "=== report ==="
FENCE_CLOSE = "=== end report ==="
_KV = re.compile(r"^([a-z][a-z -]*?): (.*)$")


def app_text(
    replace: Mapping[int, str] | None = None, insert: Mapping[int, str] | None = None
) -> str:
    """Return the 40-line `src/app.py`; `insert[n]` adds a line after line n (1-based)."""
    lines = [f"line {i}" for i in range(1, 41)]
    for n, text in (replace or {}).items():
        lines[n - 1] = text
    for n, text in sorted((insert or {}).items(), reverse=True):
        lines.insert(n, text)
    return "\n".join(lines) + "\n"


UTIL_BASE = "def f(a, b):\n    return a\n"
UTIL_FINDINGS = "def f(a, b):\n    x = a / b\n    y = rejected_line(a)\n    return x\n"


def seed_branch(
    repo: GitRepo,
    branch: str = "feature/seed",
    *,
    util_findings: bool = False,
    big: bool = False,
) -> str:
    """Put base files on `main`, then create `branch` with a small seeded change.

    The branch adds one line to `src/app.py` after line 20 and creates `src/new.py` (3 changed
    lines). `util_findings` rewrites `src/util.py`; `big` adds a 60-line file (not a small diff).
    """
    repo.commit({APP: app_text(), UTIL: UTIL_BASE}, "base files")
    repo.branch(branch)
    files = {APP: app_text(insert={20: SEEDED}), NEW: "def new():\n    return 1\n"}
    if util_findings:
        files[UTIL] = UTIL_FINDINGS
    if big:
        files["src/big.py"] = "".join(f"value_{i} = {i}\n" for i in range(60))
    repo.commit(files, "seed the change")
    return branch


def append_commit(repo: GitRepo, path: str, line: str, msg: str | None = None) -> str:
    """Append `line` to `path` (created when absent) and commit."""
    target = repo.root / path
    old = target.read_text(encoding="utf-8") if target.exists() else ""
    return repo.commit({path: old + line + "\n"}, msg or f"edit {path}")


def current_branch(repo: GitRepo) -> str:
    return repo.run("rev-parse", "--abbrev-ref", "HEAD").strip()


def branch_dir(branch: str) -> str:
    """Expected RND-18 directory part of a branch (after the first `/`, sanitised)."""
    name = branch.split("/", 1)[1] if "/" in branch else branch
    return "/".join(re.sub(r"[^A-Za-z0-9._-]", "-", part) for part in name.split("/"))


def make_unmerged(repo: GitRepo, other: str = "main") -> None:
    """Leave the current branch in the middle of a conflicting merge with `other`."""
    mine = current_branch(repo)
    repo.checkout(other)
    repo.commit({"README.md": "other side\n"}, "other side")
    repo.checkout(mine)
    repo.commit({"README.md": "my side\n"}, "my side")
    repo.run("merge", other, check=False)


def set_remote_ref(repo: GitRepo, name: str, rev: str = "main") -> None:
    """Create `refs/remotes/<name>` (e.g. `origin/main`) pointing at `rev`, without a remote."""
    repo.run("update-ref", f"refs/remotes/{name}", rev)


def fake_gh(gh_dir: Path, *, stdout: str = "", stderr: str = "", code: int = 0) -> Path:
    """Install an executable `gh` first on PATH that logs its arguments and replies as told."""
    script = gh_dir / "gh"
    lines = ["#!/bin/sh", f'echo "$@" >> {shlex.quote(str(gh_dir / "gh.log"))}']
    if stdout:
        lines.append(f"printf '%s' {shlex.quote(stdout)}")
    if stderr:
        lines.append(f"printf '%s\\n' {shlex.quote(stderr)} >&2")
    lines.append(f"exit {code}")
    script.write_text("\n".join(lines) + "\n", encoding="utf-8")
    script.chmod(0o755)
    return script


def gh_calls(gh_dir: Path) -> list[str]:
    log = gh_dir / "gh.log"
    return log.read_text(encoding="utf-8").splitlines() if log.exists() else []


def pr_json(base: str, number: int, head: str, body: str = "") -> str:
    return json.dumps({"baseRefName": base, "number": number, "headRefName": head, "body": body})


def no_pr_stderr(branch: str = "feature/seed") -> str:
    """The message `gh pr view` prints when the branch has no pull request."""
    return f'no pull requests found for branch "{branch}"'


def hide_gh(monkeypatch: pytest.MonkeyPatch, gh_dir: Path, tmp_path: Path) -> None:
    """Make `gh` unavailable while keeping `git` reachable on PATH."""
    git = shutil.which("git")
    assert git is not None
    (gh_dir / "gh").unlink(missing_ok=True)
    only_git = tmp_path / "only-git"
    only_git.mkdir(exist_ok=True)
    if not (only_git / "git").exists():
        (only_git / "git").symlink_to(git)
    monkeypatch.setenv("PATH", f"{gh_dir}{os.pathsep}{only_git}")


@dataclass
class RepoSnap:
    """Everything `plan` must leave untouched (RND-3)."""

    index: bytes | None
    index_mtime_ns: int | None
    refs: str
    head: str
    status: str
    git_dir_entries: tuple[str, ...]


def snap(repo: GitRepo) -> RepoSnap:
    index_rel = repo.run("rev-parse", "--git-path", "index").strip()
    index = repo.root / index_rel
    git_dir = repo.root / repo.run("rev-parse", "--git-dir").strip()
    return RepoSnap(
        index=index.read_bytes() if index.exists() else None,
        index_mtime_ns=index.stat().st_mtime_ns if index.exists() else None,
        refs=repo.run("for-each-ref", "--format=%(refname) %(objectname)"),
        head=repo.run("rev-parse", "HEAD"),
        status=repo.run("--no-optional-locks", "status", "--porcelain"),
        git_dir_entries=tuple(sorted(p.name for p in git_dir.iterdir())),
    )


def tree_bytes(root: Path) -> dict[str, bytes]:
    """Return every file under `root` (relative path -> bytes)."""
    return {
        str(p.relative_to(root)): p.read_bytes() for p in sorted(root.rglob("*")) if p.is_file()
    }


@dataclass
class Out:
    """Parsed CLI output: exit code, machine lines, fenced report."""

    code: int
    out: str
    err: str
    lines: list[tuple[str, str]] = field(default_factory=list)
    report: str = ""

    def __post_init__(self) -> None:
        in_fence = False
        report: list[str] = []
        for raw in self.out.splitlines():
            if raw == FENCE_OPEN:
                in_fence = True
            elif raw == FENCE_CLOSE:
                in_fence = False
            elif in_fence:
                report.append(raw)
            elif m := _KV.match(raw):
                self.lines.append((m.group(1), m.group(2)))
        self.report = "\n".join(report)

    @property
    def keys(self) -> list[str]:
        return [k for k, _ in self.lines]

    def get(self, key: str) -> str:
        return next(v for k, v in self.lines if k == key)

    def all(self, key: str) -> list[str]:
        return [v for k, v in self.lines if k == key]

    def has(self, key: str) -> bool:
        return key in self.keys

    @property
    def args(self) -> dict[str, Any]:
        parsed: dict[str, Any] = json.loads(self.get("workflow-args"))
        return parsed

    def findings_lines(self) -> list[dict[str, Any]]:
        return [json.loads(v) for v in self.all("report-findings")]


Runner = Callable[[list[str], Path], tuple[int, str, str]]


@dataclass
class Rc:
    """One review-cycle scenario: repo, data dir and in-process CLI runner."""

    repo: GitRepo
    data_dir: Path
    runner: Runner
    gh_dir: Path
    tmp: Path
    monkeypatch: pytest.MonkeyPatch
    results_written: int = 0

    @property
    def root(self) -> Path:
        return self.repo.root.resolve()

    def state_dir(self, branch: str | None = None, target: str = "code") -> Path:
        name = branch or current_branch(self.repo)
        return self.root / "agents" / "TEMP" / branch_dir(name) / "review-cycle" / target

    def run(self, argv: list[str], cwd: Path | None = None) -> Out:
        code, out, err = self.runner(argv, cwd or self.repo.root)
        if "internal: NotImplementedError" in err:
            # `cli.main` maps unfinished modules to exit 1; keep red-stage failures uniform.
            raise NotImplementedError(err.strip().splitlines()[0])
        return Out(code, out, err)

    def cli(self, *tokens: str, cwd: Path | None = None) -> Out:
        return self.run(["cli", "--data-dir", str(self.data_dir), *tokens], cwd)

    def cont(self, target: str = "code") -> Out:
        return self.run(
            [
                "continue",
                "--data-dir",
                str(self.data_dir),
                "--state-dir",
                str(self.state_dir(target=target)),
            ]
        )

    def merge_file(self, path: Path, target: str = "code") -> Out:
        return self.run(
            [
                "merge",
                "--data-dir",
                str(self.data_dir),
                "--state-dir",
                str(self.state_dir(target=target)),
                "--result",
                str(path),
            ]
        )

    def merge(self, result: Mapping[str, Any], target: str = "code") -> Out:
        """Write `result` (a dict) to a file outside the repo and run `merge` on it."""
        self.results_written += 1
        path = self.tmp / f"result-{self.results_written}.json"
        path.write_text(json.dumps(result), encoding="utf-8")
        return self.merge_file(path, target)

    def plan_json(self, target: str = "code") -> dict[str, Any]:
        loaded: dict[str, Any] = json.loads(
            (self.state_dir(target=target) / "plan.json").read_text(encoding="utf-8")
        )
        return loaded

    def state_json(self, target: str = "code") -> dict[str, Any]:
        loaded: dict[str, Any] = json.loads(
            (self.state_dir(target=target) / "state.json").read_text(encoding="utf-8")
        )
        return loaded

    def write_state(self, state: Mapping[str, Any], target: str = "code") -> None:
        path = self.state_dir(target=target) / "state.json"
        path.write_text(json.dumps(state), encoding="utf-8")

    def outcomes(self) -> list[dict[str, Any]]:
        path = self.data_dir / "outcomes.jsonl"
        if not path.exists():
            return []
        return [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines() if x]

    def round_trip(
        self,
        edit: Callable[[], object] | None = None,
        tokens: Sequence[str] = (),
        candidates: Sequence[Mapping[str, Any]] = (),
        **result_kw: Any,
    ) -> tuple[dict[str, Any], Out]:
        """Apply `edit`, plan a round, merge a built result; return (plan, merge output).

        RPT-18 requires a typed level and, from round 2 on, an explicit scope; a round trip
        exists to run an actual round, so it fills in `high` by default, and (unless `tokens`
        already states a scope flag) the pre-RPT-18 default scope for the round about to run:
        `--full` for round 2, `--incremental` for round 3 and on.
        """
        if edit:
            edit()
        full_tokens = list(tokens)
        if not any(t in LEVELS for t in full_tokens):
            full_tokens = ["high", *full_tokens]
        state_path = self.state_dir() / "state.json"
        if state_path.exists() and not any(
            t in ("--full", "--incremental", "--fresh") for t in full_tokens
        ):
            next_round = json.loads(state_path.read_text(encoding="utf-8"))["round"] + 1
            full_tokens.append("--incremental" if next_round >= 3 else "--full")
        planned = self.cli(*full_tokens)
        assert planned.code == 0
        assert planned.get("next") == "workflow", planned.out
        plan = self.plan_json()
        merged = self.merge(build_result(plan, candidates, **result_kw))
        assert merged.code == 0, merged.err
        return plan, merged

    def run_diff_cmd(self, plan: Mapping[str, Any]) -> str:
        """Execute the plan's `scope.diff_cmd` in the repo root and return its stdout."""
        proc = subprocess.run(
            ["sh", "-c", plan["scope"]["diff_cmd"]],
            cwd=self.repo.root,
            capture_output=True,
            text=True,
            check=True,
            timeout=60,
        )
        return proc.stdout


def make_rc(
    repo: GitRepo,
    data_dir: Path,
    runner: Runner,
    gh_dir: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> Rc:
    """Create a scenario whose `gh` reports "no pull request" until a test says otherwise."""
    fake_gh(gh_dir, stderr=no_pr_stderr(), code=1)
    return Rc(repo, data_dir, runner, gh_dir, tmp_path, monkeypatch)


def raise_if_unimplemented(proc: subprocess.CompletedProcess[str]) -> None:
    """Re-raise a subprocess's `NotImplementedError` in the test process.

    Subprocess tests run `state.py`, which turns an unfinished module into exit 1 plus a
    traceback; this keeps red-stage failures uniform (`NotImplementedError` only).
    """
    if "NotImplementedError" in proc.stderr + proc.stdout:
        raise NotImplementedError(proc.stderr.strip().splitlines()[-1] if proc.stderr else "")


def assert_error(out: Out, code: int, text: str) -> None:
    """CLI-9/CLI-10: `next: stop` plus the same one-line `error:` on stdout and stderr."""
    assert out.code == code, (out.out, out.err)
    assert out.get("next") == "stop"
    message = out.get("error")
    assert text in message, message
    assert f"error: {message}" in out.err.splitlines()
