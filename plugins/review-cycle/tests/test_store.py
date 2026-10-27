"""State-dir and data-dir file access (RND-8, RND-18, ST-7, ST-8, NFR-2)."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import pytest
from review_cycle import store


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("https://u:tok@example.com/o/r.git", "https://example.com/o/r.git"),
        ("https://tok@example.com/o/r.git", "https://example.com/o/r.git"),
        ("ssh://git:secret@host.example:2222/o/r.git", "ssh://host.example:2222/o/r.git"),
        ("https://example.com/o/r.git", "https://example.com/o/r.git"),
        ("git@github.com:o/r.git", "git@github.com:o/r.git"),
        ("/srv/git/r.git", "/srv/git/r.git"),
    ],
)
def test_strip_userinfo(url: str, expected: str) -> None:
    """ST-7: `scheme://user[:pw]@host/…` loses the userinfo; scp-form is unchanged."""
    assert store.strip_userinfo(url) == expected


@pytest.mark.parametrize(
    ("branch", "expected"),
    [
        ("feature/x", "x"),
        ("feature/a/b", "a/b"),
        ("work", "work"),
        ("fix/a;b", "a-b"),
        ("fix/é", "-"),
        ("feat/-lead", "-lead"),
        ("release/v1.2_rc", "v1.2_rc"),
    ],
)
def test_state_dir_layout(tmp_path: Path, branch: str, expected: str) -> None:
    """RND-18: part after the first `/`, unsafe characters become `-`."""
    got = store.state_dir(tmp_path, branch, "code")
    assert got == tmp_path / "agents" / "TEMP" / expected / "review-cycle" / "code"


def test_state_dir_target_for_documents(tmp_path: Path) -> None:
    """RND-18: the target is the last component."""
    got = store.state_dir(tmp_path, "feature/x", "doc-docs-spec-md")
    assert got.name == "doc-docs-spec-md" and got.parent.name == "review-cycle"


@pytest.mark.parametrize(
    "branch", ["feature/..", "feature/.", "..", ".", "feature/a/../b", "feature/a..b"]
)
def test_state_dir_rejects_parent_references(tmp_path: Path, branch: str) -> None:
    """RND-18/§13: `..` never reaches the file system."""
    with pytest.raises(ValueError):
        store.state_dir(tmp_path, branch, "code")


def test_verify_dir_is_a_subdirectory(tmp_path: Path) -> None:
    """ST-2."""
    assert store.verify_dir(tmp_path / "s") == tmp_path / "s" / "verify"


def test_read_json_absent_and_present(tmp_path: Path) -> None:
    """ST-4: absent -> None."""
    assert store.read_json(tmp_path / "nope.json") is None
    (tmp_path / "a.json").write_text('{"x": [1, "ж"]}', encoding="utf-8")
    assert store.read_json(tmp_path / "a.json") == {"x": [1, "ж"]}


def test_write_json_round_trips_unicode(tmp_path: Path) -> None:
    """NFR-2."""
    target = tmp_path / "state.json"
    store.write_json(target, {"claim": "Кириллица ✓", "n": 1})
    assert json.loads(target.read_text(encoding="utf-8")) == {"claim": "Кириллица ✓", "n": 1}


def test_write_text_replaces_content(tmp_path: Path) -> None:
    """NFR-2."""
    target = tmp_path / "round-1.md"
    store.write_text(target, "one\n")
    store.write_text(target, "two\n")
    assert target.read_text(encoding="utf-8") == "two\n"


def test_writes_use_a_tmp_file_and_os_replace(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """NFR-2: tmp file next to the target, then `os.replace`."""
    calls: list[tuple[str, str]] = []
    real = os.replace

    def spy(src: Any, dst: Any) -> None:
        calls.append((str(src), str(dst)))
        real(src, dst)

    monkeypatch.setattr(os, "replace", spy)
    store.write_json(tmp_path / "a.json", {"a": 1})
    store.write_text(tmp_path / "b.md", "b")
    assert [dst for _, dst in calls] == [str(tmp_path / "a.json"), str(tmp_path / "b.md")]
    for src, dst in calls:
        assert os.path.dirname(src) == os.path.dirname(dst) and src != dst
    assert sorted(p.name for p in tmp_path.iterdir()) == ["a.json", "b.md"]


def test_failed_replace_keeps_the_old_file_and_leaves_no_partial(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """NFR-2: the previous content survives a failure at the last step."""
    target = tmp_path / "state.json"
    store.write_json(target, {"v": "old"})

    def boom(src: Any, dst: Any) -> None:
        raise OSError("disk full")

    monkeypatch.setattr(os, "replace", boom)
    with pytest.raises(OSError, match="disk full"):
        store.write_json(target, {"v": "new"})
    assert json.loads(target.read_text(encoding="utf-8")) == {"v": "old"}
    assert [p.name for p in tmp_path.iterdir()] == ["state.json"]


def test_unserialisable_object_keeps_the_old_file(tmp_path: Path) -> None:
    """NFR-2: serialisation errors never truncate the target."""
    target = tmp_path / "state.json"
    store.write_json(target, {"v": "old"})
    with pytest.raises(TypeError):
        store.write_json(target, {"v": object()})
    assert json.loads(target.read_text(encoding="utf-8")) == {"v": "old"}


def outcome(n: int) -> dict[str, Any]:
    return {"finding_id": f"F{n}", "status": "wontfix", "class": "кл", "round": n}


def test_outcomes_append_one_json_line_each(tmp_path: Path) -> None:
    """ST-7: `outcomes.jsonl`, appended in order."""
    assert store.read_outcomes(tmp_path) == []
    store.append_outcome(tmp_path, outcome(1))
    store.append_outcome(tmp_path, outcome(2))
    lines = (tmp_path / "outcomes.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2 and json.loads(lines[0]) == outcome(1)
    assert store.read_outcomes(tmp_path) == [outcome(1), outcome(2)]


def test_last_level_round_trip_and_format(tmp_path: Path) -> None:
    """ST-8: one level word plus a newline."""
    assert store.last_level(tmp_path) is None
    store.set_last_level(tmp_path, "medium")
    assert (tmp_path / "last-level").read_text(encoding="utf-8") == "medium\n"
    assert store.last_level(tmp_path) == "medium"
    store.set_last_level(tmp_path, "max")
    assert store.last_level(tmp_path) == "max"


@pytest.mark.parametrize("content", ["bogus\n", "", "HIGH\n", "high medium\n"])
def test_last_level_ignores_invalid_content(tmp_path: Path, content: str) -> None:
    """CLI-5: only the five level words count."""
    (tmp_path / "last-level").write_text(content, encoding="utf-8")
    assert store.last_level(tmp_path) is None


def test_archive_moves_the_round_files(tmp_path: Path) -> None:
    """RND-8: state, plan, round files, side files and verify/ move; `.gitignore` and older archives stay."""
    sd = tmp_path / "state"
    (sd / "verify").mkdir(parents=True)
    (sd / "archive-20260101T000000Z").mkdir()
    (sd / "archive-20260101T000000Z" / "state.json").write_text("{}", encoding="utf-8")
    for name in (
        "state.json",
        "plan.json",
        "round-1.md",
        "round-2.md",
        "doc-snapshot.md",
        "result-round-1.json",
        "verify/intent.md",
        ".gitignore",
    ):
        (sd / name).write_text(name, encoding="utf-8")
    target = store.archive(sd, "20260202T101010Z")
    assert target == sd / "archive-20260202T101010Z"
    for name in (
        "state.json",
        "plan.json",
        "round-1.md",
        "round-2.md",
        "doc-snapshot.md",
        "result-round-1.json",
        "verify/intent.md",
    ):
        assert (target / name).read_text(encoding="utf-8") == name
        assert not (sd / name).exists()
    assert not (sd / "verify").exists()
    assert (sd / ".gitignore").exists()
    assert (sd / "archive-20260101T000000Z" / "state.json").exists()
    assert not (target / "archive-20260101T000000Z").exists()


def test_failed_write_text_removes_its_tmp_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """NFR-2/RPT-14: no stray temp file after a failed replace."""
    target = tmp_path / "round-1.md"

    def boom(src: Any, dst: Any) -> None:
        raise OSError("disk full")

    monkeypatch.setattr(os, "replace", boom)
    with pytest.raises(OSError, match="disk full"):
        store.write_text(target, "new")
    assert list(tmp_path.iterdir()) == []


def test_outcomes_file_is_private(tmp_path: Path) -> None:
    """RPT-15: `outcomes.jsonl` is created 0600."""
    store.append_outcome(tmp_path, outcome(1))
    assert (tmp_path / "outcomes.jsonl").stat().st_mode & 0o777 == 0o600


def test_read_outcomes_skips_unparsable_lines(tmp_path: Path) -> None:
    """RPT-15."""
    (tmp_path / "outcomes.jsonl").write_text(
        json.dumps(outcome(1)) + '\n{"torn": \n\n[1]\n' + json.dumps(outcome(2)) + "\n",
        encoding="utf-8",
    )
    assert store.read_outcomes(tmp_path) == [outcome(1), outcome(2)]


def test_archive_name_collision_gets_a_numeric_suffix(tmp_path: Path) -> None:
    """RPT-15."""
    sd = tmp_path / "state"
    sd.mkdir()
    (sd / "state.json").write_text("one", encoding="utf-8")
    first = store.archive(sd, "20260202T101010Z")
    (sd / "state.json").write_text("two", encoding="utf-8")
    second = store.archive(sd, "20260202T101010Z")
    (sd / "state.json").write_text("three", encoding="utf-8")
    third = store.archive(sd, "20260202T101010Z")
    assert [p.name for p in (first, second, third)] == [
        "archive-20260202T101010Z",
        "archive-20260202T101010Z-2",
        "archive-20260202T101010Z-3",
    ]
    assert (second / "state.json").read_text(encoding="utf-8") == "two"


def test_write_text_keeps_crlf(tmp_path: Path) -> None:
    """RPT-15: no newline translation."""
    store.write_text(tmp_path / "d.md", "a\r\nb\r\n")
    assert (tmp_path / "d.md").read_bytes() == b"a\r\nb\r\n"
