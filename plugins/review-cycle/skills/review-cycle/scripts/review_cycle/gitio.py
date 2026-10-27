"""Git and gh subprocess access. List args only, no shell (NFR-4)."""

from __future__ import annotations

import json
import os
import shutil
import signal
import subprocess
import tempfile
from pathlib import Path

_GIT_TIMEOUT_S = 60
_GH_TIMEOUT_S = 15
_GH_ERROR_MAX = 80
_DEFAULT_BASES = ("origin/HEAD", "origin/main", "origin/master", "main", "master")

# Repo or user config must not change how diffs are rendered or parsed: file names stay raw
# (quotepath), prefixes are fixed, renames and external drivers are off.
_DIFF_CONFIG = (
    "-c",
    "core.quotepath=false",
    "-c",
    "diff.noprefix=false",
    "-c",
    "diff.mnemonicPrefix=false",
    "-c",
    "diff.renames=false",
    "-c",
    "diff.external=",
)
# Subcommand plus its forced flags. `--inter-hunk-context=0` keeps `-U0` hunks from being merged
# by a repo-local `diff.interHunkContext`.
_DIFF_COMMAND = (
    "diff",
    "--src-prefix=a/",
    "--dst-prefix=b/",
    "--no-ext-diff",
    "--no-textconv",
    "--no-color",
    "--diff-algorithm=myers",
    "--inter-hunk-context=0",
    "--no-renames",
)


def _run(
    args: list[str],
    *,
    timeout: int,
    cwd: Path | None = None,
    input: bytes | None = None,
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[bytes]:
    """Run `args` without a shell, with stdin closed unless `input` is given.

    The process gets its own process group, which is killed on timeout so helpers spawned by
    git or gh do not outlive the call.

    Raises:
        subprocess.TimeoutExpired: `timeout` seconds passed.
    """
    proc = subprocess.Popen(
        args,
        cwd=cwd,
        env=env,
        stdin=subprocess.DEVNULL if input is None else subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        start_new_session=True,
    )
    try:
        out, err = proc.communicate(input, timeout=timeout)
    except subprocess.TimeoutExpired:
        os.killpg(proc.pid, signal.SIGKILL)
        proc.communicate()
        raise
    return subprocess.CompletedProcess(args, proc.returncode, out, err)


def git(
    repo: Path, *args: str, input: bytes | None = None, env: dict[str, str] | None = None
) -> str:
    """Run `git -C repo args` (timeout 60 s, `GIT_TERMINAL_PROMPT=0`) and return stdout.

    Raises:
        subprocess.CalledProcessError: non-zero exit; `stderr` holds git's message.
        subprocess.TimeoutExpired: timeout exceeded.
    """
    proc = _run(
        ["git", "-C", str(repo), *args],
        timeout=_GIT_TIMEOUT_S,
        input=input,
        env={**os.environ, "GIT_TERMINAL_PROMPT": "0", **(env or {})},
    )
    if proc.returncode != 0:
        raise subprocess.CalledProcessError(proc.returncode, proc.args, proc.stdout, proc.stderr)
    return proc.stdout.decode("utf-8", errors="replace")


def describe_failure(exc: subprocess.CalledProcessError | subprocess.TimeoutExpired) -> str:
    """Return the one-line CLI error for a failed or timed-out `git` call (RPT-15).

    Format: `git <subcommand> failed: <first stderr line>` or
    `git <subcommand> timed out after <n> s`.
    """
    words = list(exc.cmd)[1:]
    while words and words[0] in ("-C", "-c"):
        del words[:2]
    subcommand = words[0] if words else "?"
    if isinstance(exc, subprocess.TimeoutExpired):
        return f"git {subcommand} timed out after {int(exc.timeout)} s"
    stderr = exc.stderr.decode("utf-8", errors="replace") if exc.stderr else ""
    lines = stderr.strip().splitlines()
    return f"git {subcommand} failed: {lines[0] if lines else f'exit {exc.returncode}'}"


def _git_ok(repo: Path, *args: str) -> str | None:
    """Return stdout of a git call, or None when git exits non-zero."""
    try:
        return git(repo, *args)
    except subprocess.CalledProcessError:
        return None


def git_diff(repo: Path, a: str, b: str, *, unified: int) -> str:
    """Return the forced-option diff `a`..`b` with `-U<unified>` (RND-4)."""
    return git(repo, *_DIFF_CONFIG, *_DIFF_COMMAND, "--binary", f"-U{unified}", a, b)


def diff_names(repo: Path, a: str, b: str) -> list[str]:
    """Return changed file names between `a` and `b` in `git diff --name-only -z` order."""
    out = git(repo, *_DIFF_CONFIG, *_DIFF_COMMAND, "--name-only", "-z", a, b)
    return [name for name in out.split("\0") if name]


def toplevel(cwd: Path) -> Path:
    """Return the repository root containing `cwd`."""
    return Path(git(cwd, "rev-parse", "--show-toplevel").strip())


def current_branch(repo: Path) -> str | None:
    """Return the checked-out branch name, or None on a detached HEAD."""
    out = _git_ok(repo, "symbolic-ref", "--short", "--quiet", "HEAD")
    return out.strip() if out else None


def rev_parse(repo: Path, ref: str) -> str | None:
    """Return the commit SHA `ref` resolves to, or None when it does not resolve."""
    out = _git_ok(repo, "rev-parse", "--verify", "--quiet", "--end-of-options", f"{ref}^{{commit}}")
    return out.strip() if out else None


def has_unmerged(repo: Path) -> bool:
    """Return True when the index has unmerged entries."""
    return bool(git(repo, "ls-files", "-u").strip())


def resolve_base(
    repo: Path, range_ref: str | None, pr: dict | None, gh_reason: str | None
) -> tuple[str, str]:
    """Choose the base per RND-1.

    Args:
        repo: repository root.
        range_ref: `ref` of a range target, or None.
        pr: current/target PR info from `gh_pr`, or None.
        gh_reason: why `pr` is None (RND-1.4 wording), or None.

    Returns:
        (base_ref, base_reason).

    Raises:
        RuntimeError: no base resolves; message is the CLI error text.
    """
    if range_ref is not None:
        return range_ref, "range target"
    reason = gh_reason or "no PR found via gh"
    if pr is not None:
        pr_ref = pr_base(repo, pr)
        if pr_ref is not None:
            return pr_ref, f"PR #{pr['number']}"
        reason = f"PR #{pr['number']} base origin/{pr['baseRefName']} not found"
    for candidate in _DEFAULT_BASES:
        if rev_parse(repo, candidate) is not None:
            return candidate, reason
    raise RuntimeError("no base branch found")


def pr_base(repo: Path, pr: dict) -> str | None:
    """Return `origin/<baseRefName>` of a PR when that ref exists locally, else None."""
    ref = f"origin/{pr['baseRefName']}"
    return ref if rev_parse(repo, ref) is not None else None


def merge_base(repo: Path, base_sha: str) -> str:
    """Return `git merge-base <base_sha> HEAD`."""
    return git(repo, "merge-base", "--end-of-options", base_sha, "HEAD").strip()


def snapshot_tree(repo: Path) -> str:
    """Return a tree SHA of the work tree without touching the real index or refs (RND-3).

    Side effects: `git add` writes the work tree's blobs and trees as loose objects in `.git`
    (and runs clean filters such as LFS on them). Refs, the real index and the work tree stay
    unchanged.
    """
    # A copy of the index in a temp dir outside the repo keeps the real index, refs and work
    # tree untouched. `git stash create` was rejected: it skips untracked files.
    real_index = repo / git(repo, "rev-parse", "--git-path", "index").strip()
    scratch = Path(tempfile.mkdtemp(prefix="review-cycle-index-"))
    try:
        temp_index = scratch / "index"
        if real_index.exists():
            shutil.copy2(real_index, temp_index)
        env = {"GIT_INDEX_FILE": str(temp_index)}
        git(repo, "add", "-A", env=env)
        return git(repo, "write-tree", env=env).strip()
    finally:
        shutil.rmtree(scratch, ignore_errors=True)


def show(repo: Path, rev: str, path: str) -> str | None:
    """Return the text of `path` at `rev`, or None when absent."""
    return _git_ok(repo, "show", f"{rev}:{path}")


def tracked_at_head(repo: Path, path: str) -> bool:
    """Return True when `path` exists at HEAD."""
    return _git_ok(repo, "cat-file", "-e", f"HEAD:{path}") is not None


def commit_messages(repo: Path, mb: str) -> str:
    """Return `git log --format=%B <mb>..HEAD`."""
    return git(repo, "log", "--format=%B", f"{mb}..HEAD")


def origin_url(repo: Path) -> str | None:
    """Return the `origin` remote URL, or None."""
    out = _git_ok(repo, "config", "--get", "remote.origin.url")
    return out.strip() or None if out else None


def gh_pr(repo: Path, number: int | None) -> tuple[dict | None, str | None]:
    """Query `gh pr view` (timeout 15 s).

    Args:
        repo: repository root.
        number: PR number, or None for the current branch's PR.

    Returns:
        (pr, None) with baseRefName, body, number, headRefName; or (None, reason) using the
        RND-1.4 reason wording.
    """
    args = ["gh", "pr", "view"]
    if number is not None:
        args.append(str(number))
    args += ["--json", "baseRefName,body,number,headRefName"]
    try:
        proc = _run(
            args,
            cwd=repo,
            timeout=_GH_TIMEOUT_S,
            env={**os.environ, "GIT_TERMINAL_PROMPT": "0", "GH_PROMPT_DISABLED": "1"},
        )
    except FileNotFoundError:
        return None, "gh not installed"
    except subprocess.TimeoutExpired:
        return None, f"gh error: timed out after {_GH_TIMEOUT_S}s"
    if proc.returncode != 0:
        stderr = proc.stderr.decode("utf-8", errors="replace")
        if "no pull requests found" in stderr:
            return None, "no PR found via gh"
        if "no git remotes found" in stderr:
            return None, "no remote for gh"
        lines = stderr.strip().splitlines()
        first = lines[0] if lines else f"exit {proc.returncode}"
        return None, f"gh error: {first[:_GH_ERROR_MAX]}"
    try:
        pr = json.loads(proc.stdout.decode("utf-8", errors="replace"))
    except ValueError:
        return None, "gh error: unreadable output"
    if not isinstance(pr, dict):
        return None, "gh error: unreadable output"
    return pr, None
