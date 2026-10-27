"""Pure diff helpers (RND-4, RND-5): split, normalise, diff ids, ranges, line counts."""

from __future__ import annotations

import re

import pytest
from review_cycle import diffs

TWO_FILES = """\
diff --git a/a.py b/a.py
index 1111111..2222222 100644
--- a/a.py
+++ b/a.py
@@ -1,3 +1,4 @@ def alpha():
 one
+two
 three
 four
diff --git a/b.py b/b.py
index 3333333..4444444 100644
--- a/b.py
+++ b/b.py
@@ -10,2 +10,2 @@
-old
+new
 keep
"""

U0_MULTI = """\
diff --git a/a.py b/a.py
index 1111111..2222222 100644
--- a/a.py
+++ b/a.py
@@ -2,0 +3,2 @@
+added one
+added two
@@ -7 +8 @@
-before
+after
@@ -12,2 +13,0 @@
-gone one
-gone two
diff --git a/b.py b/b.py
deleted file mode 100644
index 3333333..0000000
--- a/b.py
+++ /dev/null
@@ -1,3 +0,0 @@
-x
-y
-z
"""


def test_split_maps_chunks_to_paths_in_order() -> None:
    """RND-4: the i-th chunk belongs to the i-th path of the name list."""
    chunks = diffs.split_file_diffs(TWO_FILES, ["a.py", "b.py"])
    assert list(chunks) == ["a.py", "b.py"]
    assert chunks["a.py"].startswith("diff --git a/a.py b/a.py\n")
    assert "+two" in chunks["a.py"] and "+new" not in chunks["a.py"]
    assert chunks["b.py"].startswith("diff --git a/b.py b/b.py\n")
    assert "+new" in chunks["b.py"]


def test_split_empty_diff_gives_no_chunks() -> None:
    """RND-4: no files, no chunks."""
    assert diffs.split_file_diffs("", []) == {}


def test_split_count_mismatch_raises_value_error() -> None:
    """RND-4: chunk count differs from the name list."""
    with pytest.raises(ValueError):
        diffs.split_file_diffs(TWO_FILES, ["a.py"])
    with pytest.raises(ValueError):
        diffs.split_file_diffs(TWO_FILES, ["a.py", "b.py", "c.py"])


def test_split_ignores_diff_header_text_inside_content() -> None:
    """RND-4: only lines that start with `diff --git ` split; `+diff --git` is content."""
    text = (
        "diff --git a/n.md b/n.md\n--- a/n.md\n+++ b/n.md\n@@ -1 +1,2 @@\n"
        " keep\n+diff --git a/x b/x\n"
    )
    assert list(diffs.split_file_diffs(text, ["n.md"])) == ["n.md"]


def test_split_uses_the_name_list_not_the_header_for_unusual_paths() -> None:
    """RND-4: Cyrillic and spaced paths map by position."""
    text = (
        "diff --git a/док/файл.md b/док/файл.md\n--- a/док/файл.md\n+++ b/док/файл.md\n"
        "@@ -1 +1 @@\n-a\n+b\n"
        "diff --git a/with space.txt b/with space.txt\n--- a/with space.txt\n"
        "+++ b/with space.txt\n@@ -1 +1 @@\n-c\n+d\n"
    )
    chunks = diffs.split_file_diffs(text, ["док/файл.md", "with space.txt"])
    assert "+b" in chunks["док/файл.md"]
    assert "+d" in chunks["with space.txt"]


def test_normalise_drops_index_lines_and_reduces_hunk_headers() -> None:
    """RND-4: `index …` lines vanish; `@@ -a,b +c,d @@ ctx` becomes `@@`."""
    out = diffs.normalise(TWO_FILES)
    assert not [ln for ln in out.splitlines() if ln.startswith("index ")]
    headers = [ln for ln in out.splitlines() if ln.startswith("@@")]
    assert headers == ["@@", "@@"]
    assert "--- a/a.py" in out and "+two" in out and " keep" in out


def test_normalise_keeps_content_lines_that_look_like_headers() -> None:
    """RND-4: only real `index ` lines are dropped; an added `+index 1` stays."""
    text = "diff --git a/f b/f\nindex 1..2 100644\n@@ -1 +1,2 @@\n x\n+index 1\n"
    out = diffs.normalise(text)
    assert "+index 1" in out
    assert "index 1..2" not in out


def test_normalise_is_idempotent() -> None:
    """RND-4."""
    once = diffs.normalise(TWO_FILES)
    assert diffs.normalise(once) == once


def test_diff_id_is_sha256_hex() -> None:
    """RND-4: diff_id = sha256 of the normalised -U1 chunk."""
    assert re.fullmatch(r"[0-9a-f]{64}", diffs.diff_id(TWO_FILES))


def test_diff_id_ignores_blob_hashes_and_hunk_positions() -> None:
    """RND-5: a rebase changes `index` hashes and line numbers, not the id."""
    moved = TWO_FILES.replace("1111111..2222222", "aaaaaaa..bbbbbbb").replace(
        "@@ -1,3 +1,4 @@ def alpha():", "@@ -41,3 +45,4 @@ def other():"
    )
    assert diffs.diff_id(moved) == diffs.diff_id(TWO_FILES)


def test_diff_id_changes_with_added_line_text() -> None:
    """RND-5: any +/- line change changes the id."""
    assert diffs.diff_id(TWO_FILES.replace("+two", "+TWO")) != diffs.diff_id(TWO_FILES)


def test_diff_id_changes_with_whitespace_only_edit() -> None:
    """RND-5: whitespace counts."""
    assert diffs.diff_id(TWO_FILES.replace("+two", "+two ")) != diffs.diff_id(TWO_FILES)
    assert diffs.diff_id(TWO_FILES.replace("+two", "+  two")) != diffs.diff_id(TWO_FILES)


def test_diff_id_changes_when_added_line_moves_inside_the_file() -> None:
    """RND-5: with -U1 the context around the added line differs after it moves."""
    first = "diff --git a/f b/f\n@@ -1,3 +1,4 @@\n a\n+new\n b\n c\n"
    second = "diff --git a/f b/f\n@@ -2,3 +2,4 @@\n b\n+new\n c\n d\n"
    assert diffs.diff_id(first) != diffs.diff_id(second)


def test_changed_ranges_additions_modifications_and_deletions() -> None:
    """RND-4/FND-9: post-image ranges, inclusive; a pure deletion is (l, l) at the next line."""
    ranges = diffs.changed_ranges(U0_MULTI, ["a.py", "b.py"])
    assert ranges["a.py"] == [(3, 4), (8, 8), (14, 14)]
    assert ranges["b.py"] == [(1, 1)]


def test_changed_ranges_file_without_hunks_has_no_ranges() -> None:
    """RND-4: a binary or mode-only chunk contributes an empty list."""
    text = "diff --git a/img.bin b/img.bin\nBinary files a/img.bin and b/img.bin differ\n"
    assert diffs.changed_ranges(text, ["img.bin"]) == {"img.bin": []}


def test_changed_line_count_counts_added_and_removed_lines() -> None:
    """RND-4: scope.lines = changed +/- lines."""
    assert diffs.changed_line_count(U0_MULTI) == 2 + 2 + 2 + 3


def test_changed_line_count_ignores_file_headers_but_counts_dash_content() -> None:
    """RND-4: `---`/`+++` file headers are not content; a removed line `-- sql` is."""
    text = (
        "diff --git a/q.sql b/q.sql\n--- a/q.sql\n+++ b/q.sql\n@@ -1,2 +1,2 @@\n"
        "--- sql comment\n+++ plus plus\n"
    )
    assert diffs.changed_line_count(text) == 2


def test_changed_line_count_of_empty_diff_is_zero() -> None:
    """RND-6."""
    assert diffs.changed_line_count("") == 0


TYPE_CHANGE = """\
diff --git a/link b/link
deleted file mode 120000
index 1111111..0000000
--- a/link
+++ /dev/null
@@ -1 +0,0 @@
-target.txt
\\ No newline at end of file
diff --git a/link b/link
new file mode 100644
index 0000000..2222222
--- /dev/null
+++ b/link
@@ -0,0 +1 @@
+now a file
diff --git a/z.py b/z.py
index 3333333..4444444 100644
--- a/z.py
+++ b/z.py
@@ -1 +1 @@
-a
+b
"""


def test_split_joins_the_two_chunks_of_a_type_change() -> None:
    """RPT-15: a symlink<->file change yields two chunks for one path -> one combined diff."""
    chunks = diffs.split_file_diffs(TYPE_CHANGE, ["link", "z.py"])
    assert list(chunks) == ["link", "z.py"]
    assert chunks["link"].count("diff --git ") == 2
    assert "-target.txt" in chunks["link"] and "+now a file" in chunks["link"]
    assert chunks["z.py"].startswith("diff --git a/z.py b/z.py\n")


def test_type_change_chunk_counts_and_ranges() -> None:
    """RPT-15: line counts and ranges cover both halves of the combined chunk."""
    chunks = diffs.split_file_diffs(TYPE_CHANGE, ["link", "z.py"])
    assert diffs.changed_line_count(chunks["link"]) == 2
    assert diffs.changed_ranges(TYPE_CHANGE, ["link", "z.py"])["link"] == [(1, 1), (1, 1)]


def test_split_still_rejects_a_path_without_a_chunk() -> None:
    """RND-4: every name needs a chunk."""
    with pytest.raises(ValueError):
        diffs.split_file_diffs(TYPE_CHANGE, ["link", "z.py", "missing.py"])
