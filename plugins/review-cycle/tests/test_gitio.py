"""Git and gh access on real temporary repositories (RND-1..4, NFR-4, ST-7 inputs)."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest
from conftest import GitRepo
from helpers_git import (
    fake_gh,
    gh_calls,
    hide_gh,
    make_unmerged,
    no_pr_stderr,
    pr_json,
    set_remote_ref,
    snap,
)
from review_cycle import gitio

CYR = "док/файл.txt"


def feature_repo(repo: GitRepo) -> tuple[str, str]:
    """Branch with a modified, renamed, deleted, added, Cyrillic and binary file.

    Returns (merge-base, branch head).
    """
    repo.commit(
        {
            ".gitattributes": "*.txt diff=up\n",
            CYR: "one\ntwo\nthree\n",
            "old.txt": "keep\nkeep\nkeep\nkeep\n",
            "gone.txt": "bye\n",
        },
        "base",
    )
    mb = repo.run("rev-parse", "HEAD").strip()
    repo.branch("feature/x")
    (repo.root / "blob.bin").write_bytes(b"\x00\x01\x02binary")
    repo.run("mv", "old.txt", "renamed.txt")
    repo.run("rm", "-q", "gone.txt")
    head = repo.commit({CYR: "one\nTWO\nthree\n", "added.txt": "new\n"}, "feature work")
    return mb, head


def test_git_returns_stdout(git_repo: GitRepo) -> None:
    """NFR-4: list args, stdout text."""
    assert (
        gitio.git(git_repo.root, "rev-parse", "HEAD").strip()
        == git_repo.run("rev-parse", "HEAD").strip()
    )


def test_git_passes_stdin(git_repo: GitRepo) -> None:
    """NFR-4: `input` is fed to the process."""
    out = gitio.git(git_repo.root, "hash-object", "--stdin", input=b"hello\n")
    assert out.strip() == "ce013625030ba8dba906f756967f9e9ca394464a"


def test_git_failure_raises_called_process_error(git_repo: GitRepo) -> None:
    """NFR-4: a non-zero exit is an exception."""
    with pytest.raises(subprocess.CalledProcessError):
        gitio.git(git_repo.root, "rev-parse", "--verify", "nosuch")


def test_toplevel_resolves_from_a_subdirectory(git_repo: GitRepo) -> None:
    """ENV-5."""
    sub = git_repo.root / "deep" / "er"
    sub.mkdir(parents=True)
    assert gitio.toplevel(sub).resolve() == git_repo.root.resolve()


def test_current_branch_and_detached_head(git_repo: GitRepo) -> None:
    """CLI-7: a branch name, or None on a detached HEAD."""
    git_repo.branch("feature/a/b")
    assert gitio.current_branch(git_repo.root) == "feature/a/b"
    git_repo.run("checkout", "-q", "--detach")
    assert gitio.current_branch(git_repo.root) is None


def test_rev_parse_resolves_refs_to_commit_shas(git_repo: GitRepo) -> None:
    """CLI-7: branch, HEAD, and an annotated tag all give the commit SHA."""
    head = git_repo.run("rev-parse", "HEAD").strip()
    git_repo.run("tag", "-a", "-m", "release", "v1")
    assert gitio.rev_parse(git_repo.root, "main") == head
    assert gitio.rev_parse(git_repo.root, "HEAD") == head
    assert gitio.rev_parse(git_repo.root, "v1") == head


def test_rev_parse_unknown_ref_is_none(git_repo: GitRepo) -> None:
    """CLI-7."""
    assert gitio.rev_parse(git_repo.root, "nosuch") is None


@pytest.mark.parametrize("ref", ["--output=/tmp/x", "-h", "main..main", "main;ls"])
def test_rev_parse_never_treats_a_ref_as_an_option(git_repo: GitRepo, ref: str) -> None:
    """CLI-7/§13: `--end-of-options` and verify make hostile refs plain misses."""
    assert gitio.rev_parse(git_repo.root, ref) is None


def test_has_unmerged(git_repo: GitRepo) -> None:
    """RND-3."""
    git_repo.branch("feature/c")
    assert gitio.has_unmerged(git_repo.root) is False
    make_unmerged(git_repo)
    assert gitio.has_unmerged(git_repo.root) is True


def test_merge_base_is_the_fork_point(git_repo: GitRepo) -> None:
    """RND-2."""
    fork = git_repo.run("rev-parse", "HEAD").strip()
    git_repo.branch("feature/m")
    git_repo.commit({"a.txt": "a\n"}, "branch work")
    git_repo.checkout("main")
    git_repo.commit({"b.txt": "b\n"}, "main work")
    git_repo.checkout("feature/m")
    main_sha = git_repo.run("rev-parse", "main").strip()
    assert gitio.merge_base(git_repo.root, main_sha) == fork


def test_show_returns_text_or_none(git_repo: GitRepo) -> None:
    """RND-17: file text at a revision; absent -> None."""
    git_repo.commit({"REVIEW.md": "at most three nits\n", "док.md": "текст\n"}, "docs")
    assert gitio.show(git_repo.root, "HEAD", "REVIEW.md") == "at most three nits\n"
    assert gitio.show(git_repo.root, "HEAD", "док.md") == "текст\n"
    assert gitio.show(git_repo.root, "HEAD", "missing.md") is None
    assert gitio.show(git_repo.root, "HEAD~1", "REVIEW.md") is None


def test_tracked_at_head_means_committed(git_repo: GitRepo) -> None:
    """RND-16: only paths that exist at HEAD count."""
    git_repo.commit({"docs/a.md": "x\n"}, "docs")
    git_repo.write("docs/untracked.md", "y\n")
    git_repo.write("docs/staged.md", "z\n")
    git_repo.run("add", "docs/staged.md")
    assert gitio.tracked_at_head(git_repo.root, "docs/a.md") is True
    assert gitio.tracked_at_head(git_repo.root, "docs/untracked.md") is False
    assert gitio.tracked_at_head(git_repo.root, "docs/staged.md") is False


def test_commit_messages_cover_the_range_after_the_merge_base(git_repo: GitRepo) -> None:
    """RND-16."""
    mb = git_repo.run("rev-parse", "HEAD").strip()
    git_repo.branch("feature/msg")
    git_repo.commit({"a": "1\n"}, "first subject\n\nBody line closes #12")
    git_repo.commit({"b": "2\n"}, "second subject")
    text = gitio.commit_messages(git_repo.root, mb)
    assert "first subject" in text and "Body line closes #12" in text
    assert "second subject" in text
    assert "initial" not in text


def test_origin_url(git_repo: GitRepo) -> None:
    """ST-7."""
    assert gitio.origin_url(git_repo.root) is None
    git_repo.run("remote", "add", "origin", "https://u:tok@example.com/o/r.git")
    assert gitio.origin_url(git_repo.root) == "https://u:tok@example.com/o/r.git"


def test_diff_names_and_diff_use_forced_options(git_repo: GitRepo) -> None:
    """RND-4: raw Cyrillic names, `a/` `b/` prefixes, no renames, binary patch."""
    mb, head = feature_repo(git_repo)
    names = gitio.diff_names(git_repo.root, mb, head)
    assert names == sorted(names)
    assert set(names) == {CYR, "old.txt", "renamed.txt", "gone.txt", "added.txt", "blob.bin"}
    text = gitio.git_diff(git_repo.root, mb, head, unified=1)
    assert text.count("diff --git ") == len(names)
    assert f"diff --git a/{CYR} b/{CYR}" in text
    assert "rename from" not in text
    assert "GIT binary patch" in text


def test_git_diff_unified_zero_has_no_context(git_repo: GitRepo) -> None:
    """RND-4: -U0 for ranges/line counts."""
    mb, head = feature_repo(git_repo)
    text = gitio.git_diff(git_repo.root, mb, head, unified=0)
    assert "-two" in text and "+TWO" in text
    assert "\n one\n" not in text and "\n three\n" not in text


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("diff.noprefix", "true"),
        ("diff.mnemonicPrefix", "true"),
        ("diff.renames", "true"),
        ("diff.renames", "copies"),
        ("core.quotePath", "true"),
        ("color.ui", "always"),
        ("color.diff", "always"),
        ("diff.external", "/bin/false"),
        ("diff.up.textconv", "tr a-z A-Z"),
        ("diff.context", "9"),
    ],
)
def test_repo_config_cannot_change_diff_output(git_repo: GitRepo, key: str, value: str) -> None:
    """RND-4/§13: repo-local diff settings give byte-identical output."""
    mb, head = feature_repo(git_repo)
    before_diff = gitio.git_diff(git_repo.root, mb, head, unified=1)
    before_names = gitio.diff_names(git_repo.root, mb, head)
    git_repo.run("config", key, value)
    assert gitio.git_diff(git_repo.root, mb, head, unified=1) == before_diff
    assert gitio.diff_names(git_repo.root, mb, head) == before_names


def dirty(repo: GitRepo) -> None:
    """Staged edit, unstaged edit, untracked file, ignored file, deleted file."""
    repo.commit({".gitignore": "*.log\n", "a.txt": "a\n", "b.txt": "b\n", "c.txt": "c\n"}, "files")
    repo.write("a.txt", "a staged\n")
    repo.run("add", "a.txt")
    repo.write("b.txt", "b unstaged\n")
    repo.write("new file.txt", "untracked\n")
    repo.write("файл.txt", "кириллица\n")
    repo.write("debug.log", "ignored\n")
    (repo.root / "c.txt").unlink()


def tree_files(repo: GitRepo, tree: str) -> set[str]:
    out = repo.run("ls-tree", "-r", "--name-only", "-z", tree)
    return {n for n in out.split("\0") if n}


def test_snapshot_tree_holds_the_work_tree(git_repo: GitRepo) -> None:
    """RND-3/RND-5: staged, unstaged, untracked-non-ignored files in; ignored and deleted out."""
    dirty(git_repo)
    tree = gitio.snapshot_tree(git_repo.root)
    assert git_repo.run("cat-file", "-t", tree).strip() == "tree"
    assert tree_files(git_repo, tree) == {
        ".gitignore",
        "README.md",
        "a.txt",
        "b.txt",
        "new file.txt",
        "файл.txt",
    }
    assert git_repo.run("show", f"{tree}:a.txt") == "a staged\n"
    assert git_repo.run("show", f"{tree}:b.txt") == "b unstaged\n"


def test_snapshot_tree_leaves_index_refs_and_status_unchanged(git_repo: GitRepo) -> None:
    """RND-3: real index bytes and mtime, refs, HEAD, `git status --porcelain`, .git entries."""
    dirty(git_repo)
    snap(git_repo)
    before = snap(git_repo)
    gitio.snapshot_tree(git_repo.root)
    assert snap(git_repo) == before
    assert before.index is not None


def test_snapshot_tree_of_a_clean_work_tree_is_the_head_tree(git_repo: GitRepo) -> None:
    """RND-5: no changes, same tree."""
    assert gitio.snapshot_tree(git_repo.root) == git_repo.run("rev-parse", "HEAD^{tree}").strip()


def test_snapshot_tree_is_repeatable(git_repo: GitRepo) -> None:
    """NFR-1."""
    dirty(git_repo)
    assert gitio.snapshot_tree(git_repo.root) == gitio.snapshot_tree(git_repo.root)


def test_snapshot_tree_works_without_an_index_file(git_repo: GitRepo) -> None:
    """RND-3: no index file -> start without one, and do not create one."""
    git_repo.write("extra.txt", "x\n")
    index = git_repo.root / ".git" / "index"
    index.unlink()
    tree = gitio.snapshot_tree(git_repo.root)
    assert tree_files(git_repo, tree) == {"README.md", "extra.txt"}
    assert not index.exists()


def test_snapshot_tree_in_a_linked_worktree(git_repo: GitRepo, tmp_path: Path) -> None:
    """RND-3: the real index path comes from `rev-parse --git-path index`."""
    linked = tmp_path / "linked"
    git_repo.run("worktree", "add", "-q", str(linked), "-b", "side")
    wt = GitRepo(linked)
    wt.write("only-in-linked.txt", "x\n")
    snap(wt)
    before_main, before_wt = snap(git_repo), snap(wt)
    tree = gitio.snapshot_tree(linked)
    assert "only-in-linked.txt" in tree_files(wt, tree)
    assert snap(git_repo) == before_main
    assert snap(wt) == before_wt


def test_snapshot_tree_leaves_no_stray_files_in_the_repo(git_repo: GitRepo) -> None:
    """RND-3: the temporary index lives outside the repo."""
    dirty(git_repo)
    before = sorted(os.listdir(git_repo.root))
    gitio.snapshot_tree(git_repo.root)
    assert sorted(os.listdir(git_repo.root)) == before


PR12 = {"baseRefName": "develop", "number": 12, "headRefName": "feature/x", "body": ""}


def test_resolve_base_range_target_wins_over_a_pr(git_repo: GitRepo) -> None:
    """RND-1.1."""
    git_repo.run("branch", "release")
    set_remote_ref(git_repo, "origin/develop")
    assert gitio.resolve_base(git_repo.root, "release", PR12, None) == ("release", "range target")


def test_resolve_base_uses_the_pr_base_when_it_resolves(git_repo: GitRepo) -> None:
    """RND-1.3."""
    set_remote_ref(git_repo, "origin/develop")
    assert gitio.resolve_base(git_repo.root, None, PR12, None) == ("origin/develop", "PR #12")


def test_resolve_base_falls_back_when_the_pr_base_is_missing(git_repo: GitRepo) -> None:
    """RND-1.4: reason names the missing PR base."""
    assert gitio.resolve_base(git_repo.root, None, PR12, None) == (
        "main",
        "PR #12 base origin/develop not found",
    )


@pytest.mark.parametrize(
    "reason", ["gh not installed", "no PR found via gh", "gh error: HTTP 502: Bad gateway"]
)
def test_resolve_base_default_chain_carries_the_gh_reason(git_repo: GitRepo, reason: str) -> None:
    """RND-1.4: every gh outcome is the printed reason, verbatim."""
    assert gitio.resolve_base(git_repo.root, None, None, reason) == ("main", reason)


@pytest.mark.parametrize(
    ("present", "expected"),
    [
        ({"main"}, "main"),
        ({"master"}, "master"),
        ({"main", "master"}, "main"),
        ({"origin/main", "main"}, "origin/main"),
        ({"origin/master", "master"}, "origin/master"),
        ({"origin/main", "origin/master", "main"}, "origin/main"),
        ({"origin/HEAD", "origin/main", "main"}, "origin/HEAD"),
    ],
)
def test_resolve_base_default_chain_order(
    git_repo: GitRepo, present: set[str], expected: str
) -> None:
    """RND-1.4: origin/HEAD, origin/main, origin/master, main, master - first that resolves."""
    arrange_refs(git_repo, present)
    assert gitio.resolve_base(git_repo.root, None, None, "no PR found via gh") == (
        expected,
        "no PR found via gh",
    )


def test_resolve_base_without_any_candidate_raises(git_repo: GitRepo) -> None:
    """RND-1: none resolves -> RuntimeError carrying the CLI error text."""
    arrange_refs(git_repo, set())
    try:
        gitio.resolve_base(git_repo.root, None, None, "no PR found via gh")
    except NotImplementedError:
        raise
    except RuntimeError as exc:
        assert "no base branch found" in str(exc)
    else:
        pytest.fail("resolve_base returned although no base ref exists")


def arrange_refs(repo: GitRepo, present: set[str]) -> None:
    """Make exactly `present` (of the default-chain names) exist; HEAD moves to `work`."""
    repo.branch("work")
    for name in ("origin/main", "origin/master"):
        if name in present:
            set_remote_ref(repo, name)
    if "origin/HEAD" in present:
        repo.run("symbolic-ref", "refs/remotes/origin/HEAD", "refs/remotes/origin/main")
    if "master" in present:
        repo.run("branch", "master", "main")
    if "main" not in present:
        repo.run("branch", "-D", "main")


def test_gh_pr_current_branch(git_repo: GitRepo, fake_gh_dir: Path) -> None:
    """RND-1.3: `gh pr view --json …` for the current branch."""
    fake_gh(fake_gh_dir, stdout=pr_json("develop", 12, "feature/x", "body text"))
    pr, reason = gitio.gh_pr(git_repo.root, None)
    assert reason is None
    assert pr is not None
    assert (pr["baseRefName"], pr["number"], pr["headRefName"], pr["body"]) == (
        "develop",
        12,
        "feature/x",
        "body text",
    )
    (call,) = gh_calls(fake_gh_dir)
    assert call.startswith("pr view") and "--json" in call
    for field_name in ("baseRefName", "body", "number", "headRefName"):
        assert field_name in call


def test_gh_pr_by_number(git_repo: GitRepo, fake_gh_dir: Path) -> None:
    """CLI-4/RND-1.2: the PR number is passed to gh."""
    fake_gh(fake_gh_dir, stdout=pr_json("develop", 12, "feature/x"))
    gitio.gh_pr(git_repo.root, 12)
    assert gh_calls(fake_gh_dir)[0].startswith("pr view 12 ")


def test_gh_pr_without_a_pr(git_repo: GitRepo, fake_gh_dir: Path) -> None:
    """RND-1.4: gh's "no pull requests found" is not an error."""
    fake_gh(fake_gh_dir, stderr=no_pr_stderr(), code=1)
    assert gitio.gh_pr(git_repo.root, None) == (None, "no PR found via gh")


def test_gh_pr_without_git_remotes(git_repo: GitRepo, fake_gh_dir: Path) -> None:
    """RPT-17/RND-1: gh's "no git remotes found" becomes `no remote for gh`."""
    fake_gh(fake_gh_dir, stderr="no git remotes found", code=1)
    assert gitio.gh_pr(git_repo.root, None) == (None, "no remote for gh")


def test_gh_pr_error_reports_the_first_stderr_line(git_repo: GitRepo, fake_gh_dir: Path) -> None:
    """RND-1.4."""
    fake_gh(fake_gh_dir, stderr="HTTP 502: Bad gateway\nsecond line", code=1)
    assert gitio.gh_pr(git_repo.root, None) == (None, "gh error: HTTP 502: Bad gateway")


def test_gh_pr_error_line_is_cut_to_eighty_characters(git_repo: GitRepo, fake_gh_dir: Path) -> None:
    """RND-1.4: first stderr line, at most 80 characters."""
    fake_gh(fake_gh_dir, stderr="E" * 200, code=1)
    pr, reason = gitio.gh_pr(git_repo.root, None)
    assert pr is None
    assert reason is not None and reason.startswith("gh error: E")
    assert len(reason) - len("gh error: ") <= 80


def test_gh_pr_missing_gh(
    git_repo: GitRepo,
    fake_gh_dir: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """RND-1.4."""
    hide_gh(monkeypatch, fake_gh_dir, tmp_path)
    assert gitio.gh_pr(git_repo.root, None) == (None, "gh not installed")


def _slow_script(directory: Path, name: str, pid_file: Path) -> None:
    script = directory / name
    script.write_text(
        f"#!/bin/sh\nsleep 30 &\necho $! > {pid_file}\nwait\n",
        encoding="utf-8",
    )
    script.chmod(0o755)


def _gone(pid: int) -> bool:
    import time

    for _ in range(40):
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return True
        time.sleep(0.05)
    return False


def test_gh_timeout_is_a_reason_and_kills_the_process_group(
    git_repo: GitRepo,
    fake_gh_dir: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """RPT-15/NFR-4: a hung gh yields a reason; children of its process group are killed."""
    pid_file = tmp_path / "gh.pid"
    _slow_script(fake_gh_dir, "gh", pid_file)
    monkeypatch.setattr(gitio, "_GH_TIMEOUT_S", 1)
    assert gitio.gh_pr(git_repo.root, None) == (None, "gh error: timed out after 1s")
    assert _gone(int(pid_file.read_text(encoding="utf-8")))


def test_git_timeout_raises_and_kills_the_process_group(
    git_repo: GitRepo,
    fake_gh_dir: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """RPT-15/NFR-4."""
    pid_file = tmp_path / "git.pid"
    _slow_script(fake_gh_dir, "git", pid_file)
    monkeypatch.setattr(gitio, "_GIT_TIMEOUT_S", 1)
    with pytest.raises(subprocess.TimeoutExpired):
        gitio.git(git_repo.root, "status")
    assert _gone(int(pid_file.read_text(encoding="utf-8")))


def test_git_does_not_read_stdin(git_repo: GitRepo) -> None:
    """RPT-15: stdin is /dev/null unless input is given."""
    assert gitio.git(git_repo.root, "hash-object", "--stdin").strip() == (
        "e69de29bb2d1d6434b8b29ae775ad8c2e48c5391"
    )


def test_describe_failure_names_subcommand_and_first_stderr_line(git_repo: GitRepo) -> None:
    """RPT-15."""
    with pytest.raises(subprocess.CalledProcessError) as failed:
        gitio.git(git_repo.root, "rev-parse", "--verify", "nosuch")
    assert gitio.describe_failure(failed.value).startswith("git rev-parse failed: ")
    timeout = subprocess.TimeoutExpired(["git", "-C", "/r", "-c", "a=b", "diff", "x"], 60)
    assert gitio.describe_failure(timeout) == "git diff timed out after 60 s"
