"""Pure helpers over unified-diff text (RND-4, RND-5)."""

from __future__ import annotations

import hashlib
import re

_FILE_HEADER = "diff --git "
_HUNK_HEADER = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,(\d+))? @@")


def _lines(text: str) -> list[str]:
    """Split at `\\n` only: `str.splitlines` also splits at form feeds and U+2028 in file content."""
    parts = text.split("\n")
    lines = [part + "\n" for part in parts[:-1]]
    return lines + [parts[-1]] if parts[-1] else lines


def _header_path(header: str) -> str | None:
    """Return the path of a `diff --git a/P b/P` line, or None (quoted or unusual header)."""
    rest = header.rstrip("\n").removeprefix(_FILE_HEADER)
    path = rest[2 : (len(rest) - 5) // 2 + 2]
    return path if rest == f"a/{path} b/{path}" else None


def split_file_diffs(diff: str, paths: list[str]) -> dict[str, str]:
    """Split a multi-file diff at `diff --git ` lines and map each chunk to its path.

    A chunk is paired with the path named in its header; a header that cannot be read is paired
    with the path after the previous chunk's. A type change (symlink <-> file) yields two chunks
    for one path; they are joined into one combined file diff.

    Args:
        diff: output of one `git diff` call.
        paths: the file names of that diff, in diff order.

    Returns:
        Mapping path -> that file's diff chunk(s), in `paths` order.

    Raises:
        ValueError: a chunk has no path or a path has no chunk.
    """
    position = {path: i for i, path in enumerate(paths)}
    joined: dict[str, str] = {}
    last = -1
    for line in _lines(diff):
        if line.startswith(_FILE_HEADER):
            named = _header_path(line)
            last = position[named] if named in position else last + 1
            if last >= len(paths):
                raise ValueError(f"diff has more chunks than the {len(paths)} paths")
            joined[paths[last]] = joined.get(paths[last], "") + line
        elif joined:
            joined[paths[last]] += line
    if len(joined) != len(paths):
        raise ValueError(f"diff has chunks for {len(joined)} of {len(paths)} paths")
    return {path: joined[path] for path in paths}


def normalise(file_diff: str) -> str:
    """Drop `index …` lines and reduce every `@@ … @@…` header to `@@`."""
    kept: list[str] = []
    in_hunk = False
    for line in _lines(file_diff):
        if line.startswith(_FILE_HEADER):
            in_hunk = False
        elif line.startswith("@@"):
            in_hunk = True
            line = "@@\n" if line.endswith("\n") else "@@"
        elif not in_hunk and line.startswith("index "):
            continue
        kept.append(line)
    return "".join(kept)


def diff_id(file_diff_u1: str) -> str:
    """Return sha256 hex of `normalise(file_diff_u1)`; `file_diff_u1` is a `-U1` chunk."""
    # -U1 (not -U0): one context line makes a moved added line produce a different id, while
    # base changes two or more lines away from a hunk leave it untouched (RND-5).
    return hashlib.sha256(normalise(file_diff_u1).encode("utf-8")).hexdigest()


def changed_ranges(diff_u0: str, paths: list[str]) -> dict[str, list[tuple[int, int]]]:
    """Return post-image changed line ranges per path from a `-U0` diff (inclusive).

    A pure deletion is the range `(l, l)` at the line that follows it.
    """
    ranges: dict[str, list[tuple[int, int]]] = {path: [] for path in paths}
    chunks = split_file_diffs(diff_u0, paths)
    for path, chunk in chunks.items():
        for line in chunk.split("\n"):
            match = _HUNK_HEADER.match(line)
            if match is None:
                continue
            start = int(match.group(1))
            count = 1 if match.group(2) is None else int(match.group(2))
            if count == 0:
                ranges[path].append((start + 1, start + 1))
            else:
                ranges[path].append((start, start + count - 1))
    return ranges


def changed_line_count(diff_u0: str) -> int:
    """Return the number of added plus removed lines in a `-U0` diff."""
    total = 0
    in_hunk = False
    for line in diff_u0.split("\n"):
        if line.startswith(_FILE_HEADER):
            in_hunk = False
        elif line.startswith("@@"):
            in_hunk = True
        elif in_hunk and line[:1] in ("+", "-"):
            total += 1
    return total
