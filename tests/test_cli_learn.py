import json
import os
import subprocess
import sys

from cfgmerge.learn import learn, learn_from_git
from cfgmerge.policy import Policy


def run(*a, cwd=None):
    root = os.path.dirname(os.path.dirname(__file__))
    env = {**os.environ, "PYTHONPATH": root}
    return subprocess.run([sys.executable, "-m", "cfgmerge", *a], capture_output=True, text=True, cwd=cwd, env=env)


def test_cli_merge_and_exit_codes(tmp_path):
    (tmp_path / "b.yaml").write_text("a: 1\nb: 2\n")
    (tmp_path / "o.yaml").write_text("a: 9\nb: 2\n")
    (tmp_path / "t.yaml").write_text("a: 1\nb: 7\n")
    r = run("merge", "b.yaml", "o.yaml", "t.yaml", cwd=tmp_path)
    assert r.returncode == 0 and r.stdout == "a: 9\nb: 7\n"
    (tmp_path / "t2.yaml").write_text("a: 5\nb: 2\n")
    r = run("merge", "b.yaml", "o.yaml", "t2.yaml", cwd=tmp_path)
    assert r.returncode == 1 and "<<<<<<<" in r.stdout and "conflict" in r.stderr


def test_cli_diff(tmp_path):
    (tmp_path / "a.json").write_text('{"x": 1, "l": [{"name": "a", "v": 1}]}')
    (tmp_path / "b.json").write_text('{"x": 2, "l": [{"name": "a", "v": 2}, {"name": "b", "v": 1}]}')
    r = run("diff", "a.json", "b.json", cwd=tmp_path)
    out = r.stdout
    assert "~ x: 1 -> 2" in out and "l.[a].v" in out and "+ l.[b]" in out


def test_learn_from_synthetic_history():
    v = [{"deps": ["a", "b", "c"] + [f"d{j}" for j in range(i)],
          "svc": {"image": f"i{i}", "tag": f"t{i}", "port": 80},
          "items": [{"name": "web", "n": i}, {"name": "db", "n": 1}]} for i in range(8)]
    p = learn(v)
    assert p.identity.get("items") == ["name"]
    assert "deps" in p.sorted and "svc" in p.atomic


def test_learned_atomic_makes_halfmerges_conflict():
    from cfgmerge.merge import merge
    p = Policy(atomic={"svc"})
    b = {"svc": {"image": "i1", "tag": "t1", "port": 80}}
    o = {"svc": {"image": "i2", "tag": "t1", "port": 80}}
    t = {"svc": {"image": "i1", "tag": "t2", "port": 80}}
    assert not merge(b, o, t).conflicts                   # without policy: clean field merge
    assert merge(b, o, t, p).conflicts[0].kind == "atomic"


def test_learn_from_git(tmp_path):
    def git(*a):
        subprocess.run(["git", "-C", str(tmp_path), *a], check=True, capture_output=True)
    git("init", "-q"); git("config", "user.email", "t@t"); git("config", "user.name", "t")
    for i in range(6):
        (tmp_path / "c.json").write_text(json.dumps(
            {"items": [{"name": "w", "n": i}, {"name": "d", "n": 1}], "deps": ["a", "b", "c"]}))
        git("add", "-A"); git("commit", "-qm", f"v{i}")
    p = learn_from_git(str(tmp_path), "c.json")
    assert p.identity.get("items") == ["name"]


def test_affinity_suggests_but_only_autoresolves_when_confident():
    from cfgmerge.merge import merge
    weak = Policy(affinity={"v": {"ours": 8, "theirs": 1, "novel": 1}})
    r = merge({"v": 1}, {"v": 2}, {"v": 3}, weak)
    assert r.conflicts and r.conflicts[0].suggestion == "ours"
    r = merge({"v": 1}, {"v": 2}, {"v": 3}, weak, auto_affinity=True)
    assert r.conflicts                                  # 80% < 95%: stays a conflict
    strong = Policy(affinity={"v": {"ours": 12}})
    r = merge({"v": 1, "k": 1}, {"v": 2, "k": 1}, {"v": 3, "k": 5}, strong, auto_affinity=True)
    assert not r.conflicts and r.merged == {"v": 2, "k": 5}
    assert ("affinity", "v") in r.notes


def test_affinity_learned_from_git_merges(tmp_path):
    def git(*a):
        return subprocess.run(["git", "-C", str(tmp_path), *a], capture_output=True, text=True)
    git("init", "-q", "-b", "main"); git("config", "user.email", "t@t"); git("config", "user.name", "t")
    (tmp_path / "g.properties").write_text("ver=0\nother=0\n")
    git("add", "-A"); git("commit", "-qm", "0")
    for i in range(1, 5):                              # merge-forward: human always keeps main's `ver`
        git("checkout", "-q", "-b", f"rel{i}")
        (tmp_path / "g.properties").write_text(f"ver=rel{i}\nother=0\n")
        git("commit", "-qam", f"rel{i}")
        git("checkout", "-q", "main")
        (tmp_path / "g.properties").write_text(f"ver=main{i}\nother=0\n")
        git("commit", "-qam", f"main{i}")
        git("merge", "--no-commit", "--no-ff", f"rel{i}")
        (tmp_path / "g.properties").write_text(f"ver=main{i}\nother=0\n")
        git("add", "-A"); git("commit", "-qm", f"merge{i}")
    from cfgmerge.learn import learn_affinity
    aff = learn_affinity(str(tmp_path), "g.properties")
    assert aff.get("ver", {}).get("ours", 0) >= 3
