"""Tests for resolve_git_dir — worktree/submodule-safe git dir discovery."""

from pathlib import Path
import shutil
import subprocess

import pytest

from batho.modules.graph.incremental import resolve_git_dir


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True, text=True)


@pytest.fixture
def git_repo(tmp_path: Path) -> Path:
    if shutil.which("git") is None:
        pytest.skip("git not installed")
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init")
    _git(repo, "config", "user.email", "t@t.dev")
    _git(repo, "config", "user.name", "T")
    (repo / "f.txt").write_text("x")
    _git(repo, "add", "f.txt")
    _git(repo, "commit", "-m", "init")
    if resolve_git_dir(repo) is None:
        pytest.skip("git not reachable via batho's restricted PATH")
    return repo


def test_normal_repo(git_repo: Path):
    git_dir, common_dir = resolve_git_dir(git_repo)
    assert git_dir == (git_repo / ".git").resolve()
    assert common_dir == git_dir
    assert (git_dir / "index").exists()


def test_non_git_dir(tmp_path: Path):
    plain = tmp_path / "plain"
    plain.mkdir()
    assert resolve_git_dir(plain) is None


def test_linked_worktree(git_repo: Path, tmp_path: Path):
    wt = tmp_path / "linked-wt"
    _git(git_repo, "worktree", "add", str(wt), "-b", "wt-branch")
    result = resolve_git_dir(wt)
    assert result is not None
    git_dir, common_dir = result
    # Private dir lives under the main repo's .git/worktrees/<id>
    assert "worktrees" in git_dir.parts
    assert common_dir == (git_repo / ".git").resolve()
    # Private dir holds this worktree's index + HEAD
    assert (git_dir / "HEAD").exists()
    # Shared refs live under common_dir
    assert (common_dir / "refs").exists()


def test_bare_repo_returns_none(tmp_path: Path):
    if shutil.which("git") is None:
        pytest.skip("git not installed")
    bare = tmp_path / "bare.git"
    subprocess.run(["git", "init", "--bare", str(bare)], check=True, capture_output=True)
    assert resolve_git_dir(bare) is None
