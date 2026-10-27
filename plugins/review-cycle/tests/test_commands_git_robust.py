"""`plan` against awkward repositories (RND-3, RND-4, NFR-4)."""

from __future__ import annotations

import os
import subprocess
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from conftest import GitRepo
from helpers_git import APP, NEW, UTIL, Rc, assert_error, make_rc, seed_branch, snap

CYR = "док/файл.py"


@pytest.fixture
def rc(
    git_repo: GitRepo,
    data_dir: Path,
    run_cli: Callable[[list[str], Path], tuple[int, str, str]],
    fake_gh_dir: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> Rc:
    return make_rc(git_repo, data_dir, run_cli, fake_gh_dir, tmp_path, monkeypatch)


def awkward_branch(rc: Rc) -> None:
    """Cyrillic and spaced paths, a rename, a deletion, a binary file and an added line."""
    seed_branch(rc.repo)
    rc.repo.run("mv", UTIL, "src/helper.py")
    rc.repo.run("rm", "-q", "README.md")
    (rc.repo.root / "blob.bin").write_bytes(b"\x00\x01binary")
    rc.repo.commit({CYR: "x = 1\n", "with space.py": "y = 2\n"}, "awkward files")


def fingerprint_of_plan(rc: Rc) -> dict[str, Any]:
    plan = rc.plan_json()
    return {
        "change_id": plan["change_id"],
        "file_ids": plan["file_ids"],
        "files": sorted(plan["scope"]["files"]),
        "lines": plan["scope"]["lines"],
    }


def test_plan_leaves_index_refs_and_status_unchanged(rc: Rc) -> None:
    """RND-3: staged, unstaged, untracked and ignored files; nothing in the repo moves."""
    seed_branch(rc.repo)
    rc.repo.commit({".gitignore": "*.log\n"}, "ignore logs")
    rc.repo.write(APP, "staged\n")
    rc.repo.run("add", APP)
    rc.repo.write(UTIL, "unstaged\n")
    rc.repo.write("untracked.py", "u = 1\n")
    rc.repo.write("debug.log", "ignored\n")
    snap(rc.repo)
    before = snap(rc.repo)
    assert rc.cli("high").get("next") == "workflow"
    after = snap(rc.repo)
    assert after == before
    assert after.index is not None


def test_plan_in_a_repo_without_an_index_file(rc: Rc) -> None:
    """RND-3: no index file -> works from the work tree and does not create one."""
    seed_branch(rc.repo)
    index = rc.repo.root / ".git" / "index"
    index.unlink()
    out = rc.cli("high")
    assert out.get("next") == "workflow"
    assert set(rc.plan_json()["file_ids"]) == {APP, NEW}
    assert not index.exists()


def test_cyrillic_spaced_renamed_and_binary_paths(rc: Rc) -> None:
    """RND-4: names are raw, renames are delete + add, binary files have an id."""
    awkward_branch(rc)
    out = rc.cli("high")
    assert out.code == 0, out.err
    ids = rc.plan_json()["file_ids"]
    assert {CYR, "with space.py", "src/helper.py", UTIL, "README.md", "blob.bin"} <= set(ids)
    assert not [p for p in ids if p.startswith('"')]


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("diff.noprefix", "true"),
        ("diff.mnemonicPrefix", "true"),
        ("diff.renames", "copies"),
        ("core.quotePath", "true"),
        ("color.ui", "always"),
        ("diff.external", "/bin/false"),
    ],
)
def test_repo_local_diff_config_does_not_change_ids_or_ranges(rc: Rc, key: str, value: str) -> None:
    """RND-4/§13: identical change id, file ids, scope files and lines."""
    awkward_branch(rc)
    rc.cli("high")
    baseline = fingerprint_of_plan(rc)
    rc.repo.run("config", key, value)
    assert rc.cli("high").code == 0
    assert fingerprint_of_plan(rc) == baseline


def test_symlink_replaced_by_a_file_and_back(rc: Rc) -> None:
    """RPT-15: a type change is two diff chunks for one path; plan must not crash."""
    rc.repo.commit({"target.txt": "t\n", "plain.txt": "p\n"}, "targets")
    os.symlink("target.txt", rc.repo.root / "link")
    rc.repo.run("add", "link")
    rc.repo.run("commit", "-q", "-m", "add link")
    rc.repo.branch("feature/types")
    (rc.repo.root / "link").unlink()
    rc.repo.write("link", "now a regular file\n")
    (rc.repo.root / "plain.txt").unlink()
    os.symlink("target.txt", rc.repo.root / "plain.txt")
    rc.repo.run("add", "-A")
    rc.repo.run("commit", "-q", "-m", "swap types")
    out = rc.cli("high")
    assert out.code == 0, out.err
    plan = rc.plan_json()
    assert {"link", "plain.txt"} <= set(plan["file_ids"])
    assert plan["scope"]["lines"] >= 4


def test_unreadable_untracked_file_is_a_git_error(rc: Rc) -> None:
    """RPT-15: a failing git call is `error: git <sub> failed: <first stderr line>`, exit 1."""
    seed_branch(rc.repo)
    secret = rc.repo.write("secret.txt", "x\n")
    secret.chmod(0)
    try:
        out = rc.cli()
    finally:
        secret.chmod(0o644)
    assert out.code == 1 and out.get("next") == "stop"
    assert out.get("error").startswith("git add failed: ")
    assert f"error: {out.get('error')}" in out.err.splitlines()


def test_a_hung_git_is_a_timeout_error(rc: Rc) -> None:
    """RPT-15: `error: git <sub> timed out after <n> s`, exit 1."""
    from review_cycle import gitio

    seed_branch(rc.repo)
    script = rc.gh_dir / "git"
    script.write_text("#!/bin/sh\nsleep 30\n", encoding="utf-8")
    script.chmod(0o755)
    rc.monkeypatch.setattr(gitio, "_GIT_TIMEOUT_S", 1)
    assert_error(rc.cli(), 1, "git rev-parse timed out after 1 s")


def test_diff_cmd_works_from_any_directory(rc: Rc) -> None:
    """RPT-15: `git -C <repo_root> … --no-ext-diff --no-textconv`."""
    seed_branch(rc.repo)
    rc.cli("high")
    cmd = rc.plan_json()["scope"]["diff_cmd"]
    assert cmd.startswith(f"git -C {rc.root} -c core.quotepath=false diff --no-ext-diff ")
    assert "--no-textconv" in cmd
    proc = subprocess.run(
        ["sh", "-c", cmd], cwd=rc.repo.root / "src", capture_output=True, text=True, check=True
    )
    assert "+def new():" in proc.stdout


def test_data_dir_that_cannot_be_created_is_exit_three(rc: Rc, tmp_path: Path) -> None:
    """RPT-15: the data dir is created up front; failure -> exit 3."""
    seed_branch(rc.repo)
    blocker = tmp_path / "a-file"
    blocker.write_text("x", encoding="utf-8")
    rc.data_dir = blocker / "data"
    out = rc.cli()
    assert out.code == 3 and out.get("next") == "stop"
    assert not rc.state_dir().exists()
