"""Level suggested from a code change's radius: its size, breadth and sensitive paths (RPT-18)."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import PurePosixPath

from review_cycle.levels import SMALL_DIFF_MAX_FILES, SMALL_DIFF_MAX_LINES
from review_cycle.rounds import count_noun

# `max` is left out: Anthropic keeps it for an explicit request (`/code-review`, effort docs).
SUGGESTED_LEVELS = ("low", "medium", "high", "xhigh")
# Upper bounds of low, medium and high. Lines: the small-diff limit (Anthropic Code Review's
# under-50-line PRs mostly come back clean), the 200-line review target (Cisco/SmartBear,
# GitLab), the 500-line large-change border (Kubernetes size/XL, GitLab, Danger). Files: the
# small-diff limit, 10 (90% of Google's changes touch fewer), 30 (Greptile's escalation example).
# Sources and the rejected options: README "Suggested level"; tune from HANDOFF §11 runs.
LINE_BORDERS = (SMALL_DIFF_MAX_LINES, 200, 500)
FILE_BORDERS = (SMALL_DIFF_MAX_FILES, 10, 30)
SENSITIVE_FLOOR = SUGGESTED_LEVELS.index("high")
# `medium` is the lowest level with the rules lens, the one that catches docs gone stale.
DOCS_ONLY_CAP = SUGGESTED_LEVELS.index("medium")

_DOC_SUFFIXES = frozenset({".md", ".mdx", ".markdown", ".rst", ".txt", ".adoc"})
_MIGRATION_DIRS = frozenset({"migrations", "migration", "migrate"})
_CI_PREFIXES = (".github/workflows/", ".circleci/", ".buildkite/")
_CI_NAMES = frozenset({".gitlab-ci.yml", "Jenkinsfile", "azure-pipelines.yml"})
_AUTH_WORDS = frozenset(
    {"auth", "authn", "authz", "authentication", "authorization", "security", "permissions"}
)
_KIND_ORDER = ("migrations", "CI", "infra", "auth")


def _band(value: int, borders: tuple[int, ...]) -> int:
    return sum(value > border for border in borders)


def _is_doc(path: str) -> bool:
    return PurePosixPath(path).suffix.lower() in _DOC_SUFFIXES


def _sensitive_kind(path: str) -> str | None:
    p = PurePosixPath(path)
    dirs = {part.lower() for part in p.parts[:-1]}
    if dirs & _MIGRATION_DIRS:
        return "migrations"
    if path.startswith(_CI_PREFIXES) or p.name in _CI_NAMES:
        return "CI"
    if p.name.startswith("Dockerfile") or p.suffix == ".tf":
        return "infra"
    if dirs & _AUTH_WORDS or p.name.split(".", 1)[0].lower() in _AUTH_WORDS:
        return "auth"
    return None


def suggest_level(paths: Sequence[str], lines: int) -> tuple[str, str]:
    """Suggest a review level for a code change and say why.

    The level is the higher of the line band and the file band. Any sensitive non-doc path
    (migrations, CI, infra, auth) lifts it to at least `high`; a change made only of docs is
    capped at `medium`. `max` is never suggested.

    Args:
        paths: changed files, lock files already left out.
        lines: changed +/- lines of `paths`.

    Returns:
        (level, reason), e.g. `("high", "12 lines, 1 file; sensitive: migrations")`.
    """
    rank = max(_band(lines, LINE_BORDERS), _band(len(paths), FILE_BORDERS))
    code = [path for path in paths if not _is_doc(path)]
    kinds = {_sensitive_kind(path) for path in code}
    notes: list[str] = []
    if paths and not code:
        rank = min(rank, DOCS_ONLY_CAP)
        notes.append("docs only")
    if kinds - {None}:
        rank = max(rank, SENSITIVE_FLOOR)
        notes.append("sensitive: " + ", ".join(k for k in _KIND_ORDER if k in kinds))
    reason = f"{count_noun(lines, 'line')}, {count_noun(len(paths), 'file')}"
    return SUGGESTED_LEVELS[rank], "; ".join([reason, *notes])
