"""Markdown section handling for document mode (DOC-1..DOC-4)."""

from __future__ import annotations

import hashlib
import re
from collections.abc import Iterable, Mapping

_SLUG_MAX = 80
_HEADING = re.compile(r"^(#{1,6}) +(.*?)(?: +#+)?\s*$")
_TRAILING_BLANK = re.compile(r"(?:\r?\n[ \t]*)*\Z")


def _lines(text: str) -> list[str]:
    """Split at `\\n` only, keeping line ends; `str.splitlines` also splits at form feeds."""
    parts = text.split("\n")
    lines = [part + "\n" for part in parts[:-1]]
    return lines + [parts[-1]] if parts[-1] else lines


def _split(text: str) -> list[tuple[str, str]]:
    """Return (key, section text) pairs in document order, headings inside fences ignored."""
    pairs: list[tuple[str, list[str]]] = []
    path: list[tuple[int, str]] = []
    seen: dict[str, int] = {}
    fence: str | None = None
    current: list[str] = []
    key = "(preamble)"
    for line in _lines(text):
        marker = line.lstrip()[:3]
        if fence is None and marker in ("```", "~~~"):
            fence = marker
        elif fence is not None and marker == fence:
            fence = None
        match = _HEADING.match(line) if fence is None and marker not in ("```", "~~~") else None
        if match is None:
            current.append(line)
            continue
        pairs.append((key, current))
        level = len(match.group(1))
        while path and path[-1][0] >= level:
            path.pop()
        path.append((level, match.group(2)))
        key = " > ".join(title for _, title in path)
        seen[key] = seen.get(key, 0) + 1
        if seen[key] > 1:
            key = f"{key} #{seen[key]}"
        current = [line]
    pairs.append((key, current))
    return [(k, "".join(body)) for k, body in pairs if k != "(preamble)" or "".join(body).strip()]


def sections(text: str) -> dict[str, str]:
    """Split Markdown into sections keyed by ` > `-joined heading path (DOC-2).

    Headings inside code fences are ignored; duplicate keys get ` #2`, ` #3`; text before the
    first heading is `(preamble)`.
    """
    return {key: body for key, body in _split(text)}


def section_hashes(text: str) -> dict[str, str]:
    """Return sha256 hex of each section's text, keyed like `sections`."""
    return {
        key: hashlib.sha256(_TRAILING_BLANK.sub("", body).encode("utf-8")).hexdigest()
        for key, body in _split(text)
    }


def changed_sections(prev: Mapping[str, str], cur: Mapping[str, str]) -> list[str]:
    """Return keys of `cur` whose hash differs from `prev` or that are new."""
    return [key for key, digest in cur.items() if prev.get(key) != digest]


def doc_slug(relpath: str) -> str:
    """Return the state-dir slug of a document path (DOC-1)."""
    slug = re.sub("[^a-z0-9]+", "-", relpath.lower()).strip("-")
    if len(slug) > _SLUG_MAX:
        digest = hashlib.sha256(relpath.encode("utf-8")).hexdigest()[:6]
        slug = f"{slug[: _SLUG_MAX - 7]}-{digest}"
    return slug


def path_slug(paths: Iterable[str]) -> str:
    """Return the `code-path-<slug>` target's slug for `--path` (RPT-19, RPT-20(a)).

    Applies `doc_slug` to the sorted unique `paths` joined by `+`, then always appends
    `-<sha256(joined)[:6]>`: `doc_slug` alone sanitises `/` and `-` to the same character, so
    e.g. `src/a-b` and `src/a/b` would otherwise share a slug. Order of `paths` never matters
    (sorted first). When the joined string is long enough that `doc_slug` already truncated and
    appended a hash of that same string, this returns it unchanged instead of hashing twice;
    the result is always at most `_SLUG_MAX + 7` characters.
    """
    joined = "+".join(sorted(set(paths)))
    slug = doc_slug(joined)
    digest = hashlib.sha256(joined.encode("utf-8")).hexdigest()[:6]
    return slug if slug.endswith(f"-{digest}") else f"{slug}-{digest}"


def code_target(range_ref: str | None, paths: Iterable[str]) -> str:
    """Return the code-mode state target name (RND-18; RPT-19/20 path target; RPT-21 range).

    - No range, no `--path`: `"code"`.
    - No range, with `--path`: `"code-path-<path_slug(paths)>"` (RPT-19/20, unchanged).
    - A range target (`range_ref` is the typed left-hand ref, e.g. `"HEAD~1"`), with or without
      `--path`: `"code-range-<doc_slug(range_ref)>"` plus `"-path-<doc_slug(joined paths)>"`
      when `--path` is also given, plus one trailing `"-<sha256(key)[:6]>"` covering the whole
      name (`key` = `range_ref`, or `"<range_ref>|<joined paths>"` with `--path`). The single
      trailing hash is what actually tells two targets apart: `doc_slug` alone can sanitise
      different refs (e.g. `HEAD` and `HEAD^`) to the same text.

    A range target keys on the literal ref text, not a resolved SHA, so the same typed range
    (e.g. `HEAD~1...HEAD`) keeps the same target as `HEAD` moves (RPT-21).
    """
    if range_ref is None:
        return f"code-path-{path_slug(paths)}" if paths else "code"
    joined = "+".join(sorted(set(paths)))
    key = f"{range_ref}|{joined}" if joined else range_ref
    name = f"code-range-{doc_slug(range_ref)}"
    if joined:
        name += f"-path-{doc_slug(joined)}"
    digest = hashlib.sha256(key.encode("utf-8")).hexdigest()[:6]
    return f"{name}-{digest}"
