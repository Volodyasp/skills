"""State-directory and data-directory file access. Writes are atomic (NFR-2)."""

from __future__ import annotations

import json
import os
import re
import shutil
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from review_cycle.levels import LEVELS

_USERINFO = re.compile(r"^([A-Za-z][A-Za-z0-9+.-]*://)[^/]*@")
_UNSAFE_CHAR = re.compile(r"[^A-Za-z0-9._-]")


def strip_userinfo(url: str) -> str:
    """Remove `user[:pw]@` from a `scheme://` URL; scp-form `git@host:o/r` is unchanged."""
    return _USERINFO.sub(r"\1", url)


def state_dir(repo: Path, branch: str, target: str) -> Path:
    """Return `<repo>/agents/TEMP/<branch-dir>/review-cycle/<target>/` (RND-18).

    `<branch-dir>` is the branch name after its first `/` (the whole name when it has none),
    with every character outside `[A-Za-z0-9._-]` replaced by `-` per path component.

    Raises:
        ValueError: the branch name has an empty, `.` or `..` component, or contains `..`.
    """
    parts = [_UNSAFE_CHAR.sub("-", part) for part in branch.split("/", 1)[-1].split("/")]
    if ".." in "/".join(parts) or any(part in ("", ".") for part in parts):
        raise ValueError(f"unsafe branch name: {branch}")
    return repo.joinpath("agents", "TEMP", *parts, "review-cycle", target)


def verify_dir(state_dir: Path) -> Path:
    """Return the verifier-readable subdirectory of a state dir."""
    return state_dir / "verify"


def read_json(p: Path) -> dict | None:
    """Return the parsed JSON object at `p`, or None when the file is absent."""
    try:
        text = p.read_text(encoding="utf-8")
    except FileNotFoundError:
        return None
    loaded: dict = json.loads(text)
    return loaded


def write_json(p: Path, obj: dict) -> None:
    """Write `obj` as JSON to `p` atomically (tmp file + `os.replace`)."""
    write_text(p, json.dumps(obj, ensure_ascii=False, indent=2) + "\n")


def write_text(p: Path, s: str) -> None:
    """Write `s` to `p` atomically; the temp file is removed when anything fails."""
    p.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=p.parent, prefix=f".{p.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as handle:
            handle.write(s)
        os.replace(tmp, p)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def append_outcome(data_dir: Path, line: dict) -> None:
    """Append one ST-7 record to `<data_dir>/outcomes.jsonl` (created with mode 0600)."""
    data_dir.mkdir(parents=True, exist_ok=True)
    fd = os.open(data_dir / "outcomes.jsonl", os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
    with os.fdopen(fd, "a", encoding="utf-8") as handle:
        handle.write(json.dumps(line, ensure_ascii=False) + "\n")


def read_outcomes(data_dir: Path) -> list[dict]:
    """Return the records of `outcomes.jsonl` (empty when absent); unparsable lines are skipped."""
    try:
        text = (data_dir / "outcomes.jsonl").read_text(encoding="utf-8", errors="replace")
    except FileNotFoundError:
        return []
    records: list[dict] = []
    for raw in text.split("\n"):
        try:
            record = json.loads(raw)
        except ValueError:
            continue
        if isinstance(record, dict):
            records.append(record)
    return records


def last_level(data_dir: Path) -> str | None:
    """Return the remembered level word, or None when absent or invalid."""
    try:
        word = (data_dir / "last-level").read_text(encoding="utf-8").strip()
    except FileNotFoundError:
        return None
    return word if word in LEVELS else None


def set_last_level(data_dir: Path, level: str) -> None:
    """Remember `level` in `<data_dir>/last-level` (ST-8)."""
    write_text(data_dir / "last-level", level + "\n")


def archive(state_dir: Path, ts: str) -> Path:
    """Move the round files into `<state_dir>/archive-<ts>/` and return that directory (RND-8).

    Everything except `.gitignore` and earlier `archive-*` directories moves. A name collision
    appends `-2`, `-3`, ... to the directory name.
    """
    target = state_dir / f"archive-{ts}"
    suffix = 1
    while target.exists():
        suffix += 1
        target = state_dir / f"archive-{ts}-{suffix}"
    target.mkdir(parents=True)
    for entry in sorted(state_dir.iterdir()):
        if entry == target or entry.name == ".gitignore" or entry.name.startswith("archive-"):
            continue
        shutil.move(str(entry), str(target / entry.name))
    return target


def utc_now() -> str:
    """Return the current UTC time as `YYYY-MM-DDTHH:MM:SSZ`."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
