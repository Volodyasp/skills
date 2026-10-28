"""Markdown sections, hashes and slugs for document mode (DOC-1..DOC-4)."""

from __future__ import annotations

import hashlib
import re

from review_cycle import docmode

DOC = """\
Intro text before any heading.

# Alpha
alpha body

## Beta
beta body

## Gamma
gamma body

# Delta
delta body
"""


def test_sections_keys_follow_the_heading_path() -> None:
    """DOC-2: key = heading texts joined by ` > `; text before the first heading is a preamble."""
    assert list(docmode.sections(DOC)) == [
        "(preamble)",
        "Alpha",
        "Alpha > Beta",
        "Alpha > Gamma",
        "Delta",
    ]


def test_section_text_runs_from_heading_to_the_line_before_the_next_heading() -> None:
    """DOC-2."""
    got = docmode.sections(DOC)
    assert got["Alpha"].startswith("# Alpha\nalpha body")
    assert "## Beta" not in got["Alpha"]
    assert got["Alpha > Beta"].startswith("## Beta\nbeta body")
    assert "gamma" not in got["Alpha > Beta"]
    assert got["(preamble)"].startswith("Intro text")


def test_no_preamble_key_when_the_text_starts_with_a_heading() -> None:
    """DOC-2."""
    assert "(preamble)" not in docmode.sections("# Only\nbody\n")


def test_a_deeper_level_resets_on_a_shallower_heading() -> None:
    """DOC-2: `# D` then `## B` is `D > B`, not `A > B`; skipped levels still nest."""
    text = "# A\n## B\n# D\n## B\n### C\n## E\n"
    assert list(docmode.sections(text)) == ["A", "A > B", "D", "D > B", "D > B > C", "D > E"]


def test_heading_before_any_parent_uses_its_own_text() -> None:
    """DOC-2."""
    assert list(docmode.sections("## Lonely\ntext\n")) == ["Lonely"]


def test_headings_inside_backtick_fences_are_text() -> None:
    """DOC-2: a `# heading` in a ``` fence is not a section."""
    text = "# Real\n```\n# not a heading\n## nor this\n```\nafter\n## Next\n"
    got = docmode.sections(text)
    assert list(got) == ["Real", "Real > Next"]
    assert "# not a heading" in got["Real"]


def test_headings_inside_tilde_fences_are_text() -> None:
    """DOC-2."""
    text = "# Real\n~~~\n# hidden\n~~~\n## Next\n"
    assert list(docmode.sections(text)) == ["Real", "Real > Next"]


def test_other_fence_marker_does_not_close_a_fence() -> None:
    """DOC-2: ~~~ inside a ``` fence stays inside it."""
    text = "# Real\n```\n~~~\n# still hidden\n```\n## Next\n"
    assert list(docmode.sections(text)) == ["Real", "Real > Next"]


def test_unclosed_fence_swallows_the_rest() -> None:
    """DOC-2."""
    assert list(docmode.sections("# A\n```\n# B\n## C\n")) == ["A"]


def test_duplicate_headings_get_numbered_suffixes() -> None:
    """DOC-2: second and third `Setup` under `A` become ` #2`, ` #3`."""
    text = "# A\n## Setup\none\n## Setup\ntwo\n## Setup\nthree\n"
    assert list(docmode.sections(text)) == ["A", "A > Setup", "A > Setup #2", "A > Setup #3"]
    assert "two" in docmode.sections(text)["A > Setup #2"]


def test_only_atx_headings_with_a_space_count() -> None:
    """DOC-2: `^#{1,6} `; hashtags, seven hashes and indented lines are text."""
    text = "# Head\n#hashtag\n####### seven\n # indented\ntext\n"
    assert list(docmode.sections(text)) == ["Head"]


def test_cyrillic_headings_are_keys() -> None:
    """DOC-2."""
    assert list(docmode.sections("# Обзор\n## Риски\nтекст\n")) == ["Обзор", "Обзор > Риски"]


def test_section_hashes_are_sha256_of_the_section_text() -> None:
    """DOC-2/RPT-14: hash = sha256(section text without trailing blank lines)."""
    hashes = docmode.section_hashes(DOC)
    parts = docmode.sections(DOC)
    assert set(hashes) == set(parts)
    for key, text in parts.items():
        stripped = re.sub(r"(\n[ \t]*)*\Z", "", text)
        assert hashes[key] == hashlib.sha256(stripped.encode("utf-8")).hexdigest()


def test_trailing_blank_lines_do_not_change_a_section_hash() -> None:
    """DOC-2/RPT-14: whitespace-only trailing lines and the final newline run are ignored."""
    assert docmode.section_hashes("# A\nx\n") == docmode.section_hashes("# A\nx\n\n  \n\n")
    assert docmode.section_hashes("# A\nx") == docmode.section_hashes("# A\nx\n")


def test_appending_a_section_keeps_the_previous_last_hash() -> None:
    """DOC-2/RPT-14: the former last section is not 'changed' by a new section after it."""
    before = docmode.section_hashes("# A\nx\n")
    after = docmode.section_hashes("# A\nx\n\n## New\ny\n")
    assert after["A"] == before["A"] and "A > New" in after
    assert docmode.changed_sections(before, after) == ["A > New"]


def test_editing_one_section_changes_only_its_hash() -> None:
    """DOC-4: the base of 'changed sections since the last round'."""
    before = docmode.section_hashes(DOC)
    after = docmode.section_hashes(DOC.replace("beta body", "beta body edited"))
    differing = {k for k in before if before[k] != after[k]}
    assert differing == {"Alpha > Beta"}


def test_changed_sections_returns_changed_and_new_keys_only() -> None:
    """DOC-4."""
    prev = {"A": "1", "B": "2", "C": "3"}
    cur = {"A": "1", "B": "changed", "D": "4"}
    assert sorted(docmode.changed_sections(prev, cur)) == ["B", "D"]


def test_changed_sections_is_empty_for_identical_hashes() -> None:
    """DOC-4."""
    assert docmode.changed_sections({"A": "1"}, {"A": "1"}) == []


def test_doc_slug_lowercases_and_collapses_separators() -> None:
    """DOC-1."""
    assert docmode.doc_slug("docs/Plan v2.md") == "docs-plan-v2-md"


def test_doc_slug_drops_non_ascii_runs() -> None:
    """DOC-1: [^a-z0-9]+ -> `-`, edges stripped."""
    assert docmode.doc_slug("docs/План.md") == "docs-md"


def test_doc_slug_of_exactly_eighty_characters_is_unchanged() -> None:
    """DOC-1: only slugs longer than 80 characters are shortened."""
    relpath = "a" * 77 + ".md"
    slug = docmode.doc_slug(relpath)
    assert slug == "a" * 77 + "-md"
    assert len(slug) == 80


def test_doc_slug_longer_than_eighty_is_cut_and_hashed() -> None:
    """DOC-1: slug[:73] + "-" + sha256(relpath)[:6]."""
    relpath = "docs/" + "x" * 90 + ".md"
    slug = docmode.doc_slug(relpath)
    plain = re.sub("[^a-z0-9]+", "-", relpath.lower()).strip("-")
    assert slug == plain[:73] + "-" + hashlib.sha256(relpath.encode("utf-8")).hexdigest()[:6]
    assert len(slug) == 80


def test_long_slugs_with_a_shared_prefix_stay_distinct() -> None:
    """DOC-1: the hash suffix separates paths that collide after cutting."""
    one = docmode.doc_slug("docs/" + "x" * 90 + "1.md")
    two = docmode.doc_slug("docs/" + "x" * 90 + "2.md")
    assert one != two


def test_path_slug_always_ends_in_a_hash_even_when_short() -> None:
    """RPT-20(a): unlike `doc_slug`, a short slug still gets a disambiguating hash suffix."""
    slug = docmode.path_slug(["src/a"])
    digest = hashlib.sha256(b"src/a").hexdigest()[:6]
    assert slug == f"src-a-{digest}"


def test_path_slug_sanitisation_collision_is_broken_by_the_hash() -> None:
    """RPT-20(a): `src/a-b` and `src/a/b` sanitise to the same text but must not collide."""
    one = docmode.path_slug(["src/a-b"])
    two = docmode.path_slug(["src/a/b"])
    assert one != two
    assert docmode.doc_slug("src/a-b") == docmode.doc_slug("src/a/b")  # the collision, unfixed


def test_path_slug_order_does_not_matter() -> None:
    """RPT-20(a): the paths are sorted before joining."""
    assert docmode.path_slug(["b", "a"]) == docmode.path_slug(["a", "b"])


def test_path_slug_deduplicates_paths() -> None:
    assert docmode.path_slug(["a", "a"]) == docmode.path_slug(["a"])


def test_path_slug_of_a_long_joined_string_is_not_hashed_twice() -> None:
    """RPT-20(a): when `doc_slug` already truncated and hashed, that hash is not repeated."""
    paths = ["x" * 90]
    joined = "+".join(sorted(set(paths)))
    base = docmode.doc_slug(joined)
    digest = hashlib.sha256(joined.encode("utf-8")).hexdigest()[:6]
    assert base.endswith(f"-{digest}")  # doc_slug already truncated and hashed this input
    slug = docmode.path_slug(paths)
    assert slug == base
    assert len(slug) <= 80 + 7


# --- RPT-21 code_target ---------------------------------------------------------------------


def test_code_target_with_no_range_and_no_path_is_code() -> None:
    assert docmode.code_target(None, []) == "code"


def test_code_target_pins_the_existing_path_only_naming() -> None:
    """A self-review already created `code-path-plugins-review-cycle-077560`; must not move."""
    assert docmode.code_target(None, ["plugins/review-cycle"]) == (
        "code-path-plugins-review-cycle-077560"
    )
    assert docmode.code_target(None, ["src/a"]) == f"code-path-{docmode.path_slug(['src/a'])}"


def test_code_target_range_only() -> None:
    key = "HEAD~1"
    digest = hashlib.sha256(key.encode("utf-8")).hexdigest()[:6]
    assert docmode.code_target("HEAD~1", []) == f"code-range-head-1-{digest}"


def test_code_target_range_with_path() -> None:
    key = "HEAD~1|src/a"
    digest = hashlib.sha256(key.encode("utf-8")).hexdigest()[:6]
    assert docmode.code_target("HEAD~1", ["src/a"]) == f"code-range-head-1-path-src-a-{digest}"


def test_code_target_range_path_order_and_duplicates_do_not_matter() -> None:
    assert docmode.code_target("main", ["b", "a"]) == docmode.code_target("main", ["a", "b", "a"])


def test_code_target_different_refs_that_sanitise_the_same_stay_distinct() -> None:
    """`HEAD^` and `HEAD` both sanitise to "head"; the trailing hash must separate them."""
    assert docmode.code_target("HEAD^", []) != docmode.code_target("HEAD", [])


def test_code_target_moving_head_in_a_fixed_range_keeps_the_same_target() -> None:
    """RPT-21: the target keys on the literal ref text, not a resolved SHA."""
    assert docmode.code_target("HEAD~1", []) == docmode.code_target("HEAD~1", [])


def test_closing_hash_sequences_are_not_part_of_the_heading() -> None:
    """RPT-15/DOC-2: `## Goal ##` is `Goal`; `C#` keeps its hash."""
    assert list(docmode.sections("# Spec #\n## Goal ##\n## C#\n")) == [
        "Spec",
        "Spec > Goal",
        "Spec > C#",
    ]


def test_crlf_text_sections_and_trailing_blank_stripping() -> None:
    """RPT-15/DOC-2: `\\r\\n` counts like `\\n` for headings and trailing blank lines."""
    crlf = "# A\r\nx\r\n\r\n## B\r\ny\r\n\r\n"
    assert list(docmode.sections(crlf)) == ["A", "A > B"]
    assert docmode.section_hashes("# A\r\nx\r\n") == docmode.section_hashes("# A\r\nx\r\n\r\n \r\n")
