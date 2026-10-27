"""What a plan reviews: target checks, base selection, and the code or document snapshot."""

from __future__ import annotations

import hashlib
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from review_cycle import diffs, docmode, gitio, rounds
from review_cycle.cli import PlanReq


class Stop(Exception):
    """A refusal: `message` is printed as `error:` and `code` is the exit code (CLI-10)."""

    def __init__(self, code: int, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass
class Base:
    """The base a code round is measured against (RND-1)."""

    ref: str
    reason: str
    merge_base: str
    pr: dict | None


@dataclass
class Snapshot:
    """The reviewed content of a round: a work-tree snapshot (code) or a document.

    `line_counts` holds changed +/- lines per path of the branch diff (code); `doc_*` describe
    the document (document mode); `paths` holds `--path`'s resolved repo-relative paths (RPT-19,
    code mode only), already applied to `file_ids`/`line_counts`.
    """

    mode: str
    target: str
    change_id: str
    file_ids: dict[str, str]
    head_sha: str
    base: Base | None = None
    tree_sha: str | None = None
    line_counts: dict[str, int] = field(default_factory=dict)
    doc_rel: str | None = None
    doc_text: str | None = None
    doc_sha256: str | None = None
    paths: list[str] = field(default_factory=list)


def decode_document(raw: bytes) -> str:
    """Decode document bytes the way plan and merge both must: no newline translation."""
    return raw.decode("utf-8", errors="replace")


def read_current(repo: Path, snap: Snapshot, path: str) -> str | None:
    """Return the reviewed text of `path`: the snapshot tree (code) or the document."""
    if snap.mode == "document":
        return snap.doc_text if path == snap.doc_rel else None
    return gitio.show(repo, snap.tree_sha or "", path)


def _lookup_pr(repo: Path, req: PlanReq, branch: str) -> tuple[dict | None, str | None]:
    """Run the one `gh` call of a code plan and check a PR target against the checkout."""
    if req.target_kind != "pr":
        return gitio.gh_pr(repo, None)
    pr, reason = gitio.gh_pr(repo, int(req.target or 0))
    if pr is None:
        raise Stop(1, f"PR target needs gh ({reason})")
    if pr["headRefName"] != branch:
        raise Stop(1, f"check out {pr['headRefName']} first")
    return pr, None


def _check_target(req: PlanReq, repo: Path, branch: str) -> None:
    """Refuse targets that are not the checked-out branch (CLI-7)."""
    if req.target_kind == "branch" and req.target != branch:
        raise Stop(1, f"check out {req.target} first")
    if req.target_kind == "range":
        if req.right not in (None, "HEAD", branch):
            raise Stop(1, f"check out {req.right} first")
        if gitio.rev_parse(repo, req.target or "") is None:
            raise Stop(1, f"base ref {req.target} not found")


def _choose_base(repo: Path, req: PlanReq, pr: dict | None, reason: str | None) -> tuple[str, str]:
    """Pick the base (RND-1). A PR target has no fallback chain: its base must exist locally."""
    if req.target_kind == "pr" and pr is not None:
        ref = gitio.pr_base(repo, pr)
        if ref is None:
            missing = f"origin/{pr['baseRefName']}"
            raise Stop(1, f"PR #{pr['number']} base {missing} not found; fetch it first")
        return ref, f"PR #{pr['number']}"
    range_ref = req.target if req.target_kind == "range" else None
    try:
        return gitio.resolve_base(repo, range_ref, pr, reason)
    except RuntimeError as exc:
        raise Stop(1, str(exc)) from None


def _resolve_path(repo: Path, cwd: Path, raw: str) -> str:
    """Return `raw`'s repo-relative POSIX path, without a trailing slash (RPT-19).

    Raises:
        Stop: `raw` resolves outside the repository, or to the repository root itself.
    """
    repo_resolved = repo.resolve()
    candidate = (cwd / raw).resolve()
    if candidate == repo_resolved:
        raise Stop(1, f"--path {raw} covers the whole repository; drop it")
    try:
        return candidate.relative_to(repo_resolved).as_posix()
    except ValueError:
        raise Stop(1, f"--path {raw} is outside the repository") from None


def _under_any(path: str, roots: list[str]) -> bool:
    return any(path == root or path.startswith(f"{root}/") for root in roots)


def code_snapshot(req: PlanReq, repo: Path, cwd: Path, branch: str) -> Snapshot:
    """Snapshot the work tree against its base and compute per-file diff ids (RND-1..RND-5).

    `req.paths` (RPT-19) restricts `file_ids`/`line_counts` to files equal to a resolved path or
    under `<path>/`; `change_id` is computed over the kept ids only.

    Raises:
        Stop: refused target, unmerged files, no base, no merge base, or a `--path` outside the
            repository or equal to it.
        subprocess.CalledProcessError: a git call failed (see `gitio.describe_failure`).
    """
    _check_target(req, repo, branch)
    paths = sorted({_resolve_path(repo, cwd, p) for p in req.paths})
    if gitio.has_unmerged(repo):
        raise Stop(1, "unmerged files; finish the merge first")
    pr, reason = _lookup_pr(repo, req, branch)
    base_ref, base_reason = _choose_base(repo, req, pr, reason)
    base_sha = gitio.rev_parse(repo, base_ref) or ""
    try:
        merge_base = gitio.merge_base(repo, base_sha)
    except subprocess.CalledProcessError:
        raise Stop(1, f"no merge base with {base_ref}") from None
    tree_sha = gitio.snapshot_tree(repo)
    names = gitio.diff_names(repo, merge_base, tree_sha)
    ids: dict[str, str] = {}
    counts: dict[str, int] = {}
    if names:
        try:
            u1 = diffs.split_file_diffs(
                gitio.git_diff(repo, merge_base, tree_sha, unified=1), names
            )
            u0 = diffs.split_file_diffs(
                gitio.git_diff(repo, merge_base, tree_sha, unified=0), names
            )
        except ValueError:
            raise Stop(1, "internal: diff/name list mismatch") from None
        ids = {path: diffs.diff_id(chunk) for path, chunk in u1.items()}
        counts = {path: diffs.changed_line_count(chunk) for path, chunk in u0.items()}
    if paths:
        ids = {p: v for p, v in ids.items() if _under_any(p, paths)}
        counts = {p: v for p, v in counts.items() if p in ids}
    target = f"code-path-{docmode.path_slug(paths)}" if paths else "code"
    return Snapshot(
        mode="code",
        target=target,
        change_id=rounds.change_id(ids),
        file_ids=ids,
        head_sha=gitio.rev_parse(repo, "HEAD") or "",
        base=Base(base_ref, base_reason, merge_base, pr),
        tree_sha=tree_sha,
        line_counts=counts,
        paths=paths,
    )


def _find_document(repo: Path, cwd: Path, name: str) -> Path:
    for candidate in (cwd / name, repo / name):
        try:
            if candidate.is_file():
                return candidate.resolve()
        except (OSError, ValueError):
            continue
    raise Stop(1, f"document not found: {name}")


def doc_snapshot(req: PlanReq, repo: Path, cwd: Path) -> Snapshot:
    """Read the target document (tracked or not) from its raw bytes (DOC-1, DOC-3).

    Raises:
        Stop: the document does not exist or lies outside the repository.
    """
    path = _find_document(repo, cwd, req.target or "")
    try:
        rel = path.relative_to(repo.resolve()).as_posix()
    except ValueError:
        raise Stop(1, f"document is outside the repository: {req.target}") from None
    raw = path.read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    return Snapshot(
        mode="document",
        target=f"doc-{docmode.doc_slug(rel)}",
        change_id=digest,
        file_ids={},
        head_sha=gitio.rev_parse(repo, "HEAD") or "",
        doc_rel=rel,
        doc_text=decode_document(raw),
        doc_sha256=digest,
    )
