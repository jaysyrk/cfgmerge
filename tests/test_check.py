import os
import subprocess
import sys

from cfgmerge.check import audit_texts, check_text, find_markers, semantic_summary


def test_markers_need_open_mid_and_close():
    assert find_markers("a: 1\n<<<<<<< ours\nb: 1\n=======\nb: 2\n>>>>>>> theirs\n") == [2]
    assert find_markers("a: |\n  =======\n") == []
    assert find_markers("title: ========\n") == []


def test_check_flags_unparseable_and_markers_but_not_templates():
    assert check_text("x.json", '{"a": }')[0].kind == "parse-error"
    f = check_text("x.yaml", "a: 1\n<<<<<<< ours\nb: 1\n=======\nb: 2\n>>>>>>> theirs\n")
    assert [x.kind for x in f] == ["conflict-marker"]
    assert check_text("t.yaml", "a: {{ .Values.x }}\n{{- if .y }}\nb: 1\n{{- end }}\n") == []
    assert check_text("ok.toml", 'a = "1"\n') == []


def test_audit_catches_lost_and_invalid_merges():
    base = '{"a": 1, "l": ["x"]}'
    ours = '{"a": 1, "l": ["x", "o"]}'
    theirs = '{"a": 2, "l": ["x"]}'
    assert audit_texts("c.json", base, ours, theirs, '{"a": 2, "l": ["x", "o"]}') == []
    lost = audit_texts("c.json", base, ours, theirs, '{"a": 2, "l": ["x"]}')
    assert lost and lost[0].kind == "lost-content" and "o" in lost[0].details[0]
    bad = audit_texts("c.json", base, ours, theirs, '{"a": 2, "l": ["x", "o"')
    assert bad[0].kind == "invalid-merge"


def test_audit_conflicting_value_choice_is_not_a_loss():
    base, ours, theirs = '{"a": 1}', '{"a": 2}', '{"a": 3}'
    assert audit_texts("c.json", base, ours, theirs, '{"a": 3}') == []   # a human picked a side


def _repo(tmp_path):
    def git(*a):
        subprocess.run(["git", "-C", str(tmp_path), *a], check=True, capture_output=True)
    git("init", "-q", "-b", "main"); git("config", "user.email", "t@t"); git("config", "user.name", "t")
    return git


def test_summary_is_formatting_blind(tmp_path):
    git = _repo(tmp_path)
    (tmp_path / "c.json").write_text('{"a":1,"b":[1,2]}')
    git("add", "-A"); git("commit", "-qm", "1")
    (tmp_path / "c.json").write_text('{\n  "b": [1, 2],\n  "a": 1\n}\n')       # reformatted + reordered
    git("commit", "-qam", "fmt")
    (tmp_path / "c.json").write_text('{\n  "b": [1, 2, 3],\n  "a": 2\n}\n')
    git("commit", "-qam", "real")
    s1 = semantic_summary(str(tmp_path), "HEAD~2", "HEAD~1")
    assert "formatting only" in s1
    s2 = semantic_summary(str(tmp_path), "HEAD~1", "HEAD")
    assert "~ a: 1 -> 2" in s2 and "2 semantic change" in s2


def test_audit_merge_commit_end_to_end(tmp_path):
    git = _repo(tmp_path)
    (tmp_path / "c.json").write_text('{\n  "l": [\n    "x"\n  ]\n}\n')
    git("add", "-A"); git("commit", "-qm", "base")
    git("checkout", "-qb", "f")
    (tmp_path / "c.json").write_text('{\n  "l": [\n    "x",\n    "t"\n  ]\n}\n')
    git("commit", "-qam", "t")
    git("checkout", "-q", "main")
    (tmp_path / "c.json").write_text('{\n  "l": [\n    "x",\n    "o"\n  ]\n}\n')
    git("commit", "-qam", "o")
    subprocess.run(["git", "-C", str(tmp_path), "merge", "f"], capture_output=True)
    (tmp_path / "c.json").write_text('{\n  "l": [\n    "x",\n    "t"\n  ]\n}\n')   # sloppy resolution
    git("add", "-A"); git("-c", "core.editor=true", "commit", "-qm", "merge")
    root = os.path.dirname(os.path.dirname(__file__))
    r = subprocess.run([sys.executable, "-m", "cfgmerge", "audit"], cwd=tmp_path, capture_output=True, text=True,
                       env={**os.environ, "PYTHONPATH": root})
    assert r.returncode == 1 and "lost-content" in r.stderr
