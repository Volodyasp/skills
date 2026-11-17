"""Tests for `radius`: the level suggested from a code change's size, breadth and paths (RPT-18)."""

from __future__ import annotations

import pytest
from review_cycle.radius import suggest_level


def _files(n: int) -> list[str]:
    return [f"src/m{i}.py" for i in range(n)]


@pytest.mark.parametrize(
    ("lines", "level"),
    [(0, "low"), (50, "low"), (51, "medium"), (200, "medium"), (201, "high"), (500, "high")]
    + [(501, "xhigh"), (6319, "xhigh")],
)
def test_lines_set_the_level_at_each_border(lines: int, level: str) -> None:
    assert suggest_level(_files(1), lines)[0] == level


@pytest.mark.parametrize(
    ("files", "level"),
    [(3, "low"), (4, "medium"), (10, "medium"), (11, "high"), (30, "high"), (31, "xhigh")],
)
def test_file_count_raises_the_level_at_each_border(files: int, level: str) -> None:
    assert suggest_level(_files(files), 10)[0] == level


def test_the_higher_of_the_two_bands_wins() -> None:
    assert suggest_level(_files(12), 30)[0] == "high"
    assert suggest_level(_files(2), 300)[0] == "high"


def test_max_is_never_suggested() -> None:
    level, _ = suggest_level([*_files(200), "db/migrations/1.sql"], 50_000)
    assert level == "xhigh"


@pytest.mark.parametrize(
    ("path", "kind"),
    [
        ("apps/backend/supabase/migrations/20261101_add.sql", "migrations"),
        ("db/migrate/20261101_add_users.rb", "migrations"),
        ("src/main/resources/db/migration/V2__users.sql", "migrations"),
        (".github/workflows/ci.yml", "CI"),
        (".gitlab-ci.yml", "CI"),
        ("Jenkinsfile", "CI"),
        (".circleci/config.yml", "CI"),
        ("Dockerfile", "infra"),
        ("docker/Dockerfile.prod", "infra"),
        ("infra/main.tf", "infra"),
        ("src/auth/guard.ts", "auth"),
        ("src/auth.service.ts", "auth"),
        ("app/security/policy.py", "auth"),
        ("lib/permissions.py", "auth"),
    ],
)
def test_a_sensitive_path_lifts_a_small_change_to_high(path: str, kind: str) -> None:
    level, reason = suggest_level([path], 5)
    assert level == "high"
    assert reason == f"5 lines, 1 file; sensitive: {kind}"


@pytest.mark.parametrize(
    "path", ["src/author.ts", "src/migration_helpers/x.py", "src/dockerfile_parser.py"]
)
def test_lookalike_names_are_not_sensitive(path: str) -> None:
    assert suggest_level([path], 5) == ("low", "5 lines, 1 file")


def test_sensitive_floor_never_lowers_a_bigger_level() -> None:
    assert suggest_level([*_files(40), ".github/workflows/ci.yml"], 900)[0] == "xhigh"


def test_sensitive_kinds_are_listed_in_a_fixed_order() -> None:
    paths = ["src/auth/x.ts", ".github/workflows/ci.yml", "db/migrations/1.sql"]
    assert suggest_level(paths, 20)[1] == "20 lines, 3 files; sensitive: migrations, CI, auth"


def test_docs_only_change_is_capped_at_medium() -> None:
    paths = [f"docs/part{i}.md" for i in range(40)]
    assert suggest_level(paths, 3000) == ("medium", "3000 lines, 40 files; docs only")


def test_small_docs_only_change_stays_low() -> None:
    assert suggest_level(["README.md"], 12) == ("low", "12 lines, 1 file; docs only")


def test_a_doc_inside_a_sensitive_directory_is_not_sensitive() -> None:
    assert suggest_level(["src/auth/README.md"], 5) == ("low", "5 lines, 1 file; docs only")


def test_docs_mixed_with_code_are_not_capped() -> None:
    paths = ["docs/a.md", *_files(1)]
    assert suggest_level(paths, 800) == ("xhigh", "800 lines, 2 files")


def test_no_counted_files_suggests_low() -> None:
    assert suggest_level([], 0) == ("low", "0 lines, 0 files")
