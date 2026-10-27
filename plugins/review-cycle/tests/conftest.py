"""Shared fixtures for review-cycle tests.

Run from the plugin directory:
    uv run --with pytest --with pytest-cov python -m pytest tests/ -v --cov=review_cycle

Git never sees the developer's configuration: `isolated_env` is autouse.
"""

from __future__ import annotations

import os
import subprocess
import sys
from collections.abc import Callable, Iterator
from pathlib import Path

import pytest

PLUGIN_DIR = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = PLUGIN_DIR / "skills" / "review-cycle" / "scripts"
STATE_PY = SCRIPTS_DIR / "state.py"
BIN = PLUGIN_DIR / "bin" / "review-cycle-state"
REVIEW_JS = PLUGIN_DIR / "workflows" / "review.js"
HARNESS = PLUGIN_DIR / "tests" / "js" / "harness.mjs"

_AUTHOR = {
    "GIT_AUTHOR_NAME": "Test Author",
    "GIT_AUTHOR_EMAIL": "author@example.com",
    "GIT_COMMITTER_NAME": "Test Committer",
    "GIT_COMMITTER_EMAIL": "committer@example.com",
}
_FIRST_COMMIT_TS = 1_700_000_000


@pytest.fixture(autouse=True)
def isolated_env(monkeypatch: pytest.MonkeyPatch, tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Pin git config, HOME and PATH so tests never read the developer's setup.

    Returns the fake-`gh` directory, placed first on PATH; tests drop an executable `gh` in it.
    """
    home = tmp_path_factory.mktemp("home")
    fake_bin = tmp_path_factory.mktemp("fakebin")
    for name in (
        "GIT_DIR",
        "GIT_WORK_TREE",
        "GIT_INDEX_FILE",
        "GIT_OBJECT_DIRECTORY",
        "GIT_ALTERNATE_OBJECT_DIRECTORIES",
    ):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("GIT_CEILING_DIRECTORIES", str(tmp_path_factory.getbasetemp().parent))
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", "/dev/null")
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("GIT_TERMINAL_PROMPT", "0")
    monkeypatch.setenv("PATH", f"{fake_bin}{os.pathsep}{os.environ.get('PATH', '')}")
    return fake_bin


@pytest.fixture
def fake_gh_dir(isolated_env: Path) -> Path:
    """Directory first on PATH where tests install a fake `gh`."""
    return isolated_env


class GitRepo:
    """A throwaway repository with deterministic commit dates."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self._ticks = 0

    def run(self, *git_args: str, check: bool = True) -> str:
        """Run git in the repo with fixed identity and a monotonically increasing date."""
        self._ticks += 1
        stamp = f"{_FIRST_COMMIT_TS + self._ticks * 60} +0000"
        env = {
            **os.environ,
            **_AUTHOR,
            "GIT_AUTHOR_DATE": stamp,
            "GIT_COMMITTER_DATE": stamp,
        }
        proc = subprocess.run(
            ["git", *git_args],
            cwd=self.root,
            env=env,
            capture_output=True,
            text=True,
            check=check,
            timeout=30,
        )
        return proc.stdout

    def write(self, rel: str, content: str) -> Path:
        path = self.root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        return path

    def commit(self, files: dict[str, str], msg: str) -> str:
        """Write `files`, stage everything, commit, and return the new HEAD SHA."""
        for rel, content in files.items():
            self.write(rel, content)
        self.run("add", "-A")
        self.run("commit", "-q", "--allow-empty", "-m", msg)
        return self.run("rev-parse", "HEAD").strip()

    def branch(self, name: str) -> None:
        """Create and check out branch `name` at HEAD."""
        self.run("checkout", "-q", "-b", name)

    def checkout(self, name: str) -> None:
        self.run("checkout", "-q", name)


@pytest.fixture
def git_repo(tmp_path: Path, isolated_env: Path) -> GitRepo:
    """Fresh repository on `main` with one initial commit."""
    root = tmp_path / "repo"
    root.mkdir()
    repo = GitRepo(root)
    repo.run("init", "-q", "-b", "main")
    repo.commit({"README.md": "# repo\n"}, "initial")
    return repo


@pytest.fixture
def data_dir(tmp_path: Path) -> Path:
    """Plugin data directory (`--data-dir`)."""
    path = tmp_path / "plugin-data"
    path.mkdir()
    return path


@pytest.fixture
def run_cli(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> Callable[[list[str], Path], tuple[int, str, str]]:
    """Run `cli.main(argv)` in-process from `cwd`; returns (exit code, stdout, stderr).

    Preferred for integration tests: in-process runs count for coverage. `SystemExit` (argparse)
    is converted into its exit code.
    """
    from review_cycle import cli

    def _run(argv: list[str], cwd: Path) -> tuple[int, str, str]:
        monkeypatch.chdir(cwd)
        capsys.readouterr()
        try:
            code = cli.main(argv)
        except SystemExit as exc:
            code = exc.code if isinstance(exc.code, int) else 1
        captured = capsys.readouterr()
        return code, captured.out, captured.err

    return _run


@pytest.fixture
def run_state() -> Iterator[Callable[..., subprocess.CompletedProcess[str]]]:
    """Run `state.py` as a subprocess (wrapper, version guard, few end-to-end tests)."""

    def _run(*argv: str, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(STATE_PY), *argv],
            cwd=cwd,
            capture_output=True,
            text=True,
            check=False,
            timeout=60,
        )

    yield _run
