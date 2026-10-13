import os
import subprocess
import sys

import pytest


def git(repo, *a, check=True):
    return subprocess.run(["git", "-C", str(repo), *a], capture_output=True, text=True, check=check)


@pytest.fixture
def repo(tmp_path):
    git(tmp_path, "init", "-q", "-b", "main")
    git(tmp_path, "config", "user.email", "t@t")
    git(tmp_path, "config", "user.name", "t")
    return tmp_path


def install(repo):
    root = os.path.dirname(os.path.dirname(__file__))
    exe = f"PYTHONPATH={root} {sys.executable} -m cfgmerge"
    subprocess.run([sys.executable, "-m", "cfgmerge", "install", "--repo", str(repo), "--exe", exe],
                   cwd=root, check=True, capture_output=True)


def test_git_merges_concurrent_list_appends_cleanly(repo):
    base = "# services\nitems:\n  - name: a\n    v: 1\n"
    (repo / "c.yaml").write_text(base)
    git(repo, "add", "-A"); git(repo, "commit", "-qm", "base")
    git(repo, "checkout", "-qb", "feature")
    (repo / "c.yaml").write_text(base + "  - name: c\n    v: 3\n")
    git(repo, "commit", "-qam", "add c")
    git(repo, "checkout", "-q", "main")
    (repo / "c.yaml").write_text(base + "  - name: b\n    v: 2\n")
    git(repo, "commit", "-qam", "add b")
    # plain git conflicts here...
    plain = git(repo, "merge", "--no-commit", "--no-ff", "feature", check=False)
    assert plain.returncode != 0
    git(repo, "merge", "--abort")
    # ...cfgmerge does not
    install(repo)
    r = git(repo, "merge", "--no-ff", "-m", "m", "feature", check=False)
    assert r.returncode == 0, r.stdout + r.stderr
    text = (repo / "c.yaml").read_text()
    assert "name: b" in text and "name: c" in text and "# services" in text


def test_git_conflict_exit_code_and_markers(repo):
    (repo / "c.json").write_text('{\n  "a": 1\n}\n')
    git(repo, "add", "-A"); git(repo, "commit", "-qm", "base")
    git(repo, "checkout", "-qb", "f")
    (repo / "c.json").write_text('{\n  "a": 2\n}\n')
    git(repo, "commit", "-qam", "f")
    git(repo, "checkout", "-q", "main")
    (repo / "c.json").write_text('{\n  "a": 3\n}\n')
    git(repo, "commit", "-qam", "m")
    install(repo)
    r = git(repo, "merge", "f", check=False)
    assert r.returncode != 0
    assert "<<<<<<<" in (repo / "c.json").read_text()
