import json
from cfgmerge.engine import merge_texts

BASE = "# deploy\nreplicas: 2\nimage: app:1\nports:\n  - 80\n  - 443   # tls\n"


def test_yaml_clean_merge_keeps_comments():
    ours = BASE.replace("replicas: 2", "replicas: 3").replace("  - 443   # tls\n", "  - 443   # tls\n  - 8080\n")
    theirs = BASE.replace("app:1", "app:2").replace("  - 443   # tls\n", "  - 443   # tls\n  - 9090\n")
    o = merge_texts(BASE, ours, theirs, "d.yaml")
    assert o.clean and "# tls" in o.text and "# deploy" in o.text
    assert "8080" in o.text and "9090" in o.text and "replicas: 3" in o.text and "app:2" in o.text


def test_conflict_has_markers_and_report():
    ours = BASE.replace("replicas: 2", "replicas: 3")
    theirs = BASE.replace("replicas: 2", "replicas: 5")
    o = merge_texts(BASE, ours, theirs, "d.yaml")
    assert not o.clean and "<<<<<<< ours" in o.text and ">>>>>>> theirs" in o.text
    assert o.conflicts[0].where() == "replicas"


def test_fast_paths_do_not_rewrite():
    ours = BASE + "extra: 1\n"
    o = merge_texts(BASE, ours, BASE, "d.yaml")
    assert o.text == ours and o.strategy == "fast"


def test_json_roundtrip_style():
    b = '{\n  "a": 1,\n  "l": [1, 2]\n}\n'
    o = merge_texts(b, b.replace('"a": 1', '"a": 2'), b.replace("[1, 2]", "[1, 2, 3]"), "x.json")
    assert o.clean and json.loads(o.text) == {"a": 2, "l": [1, 2, 3]}
    assert '"l": [1, 2, 3]' in o.text


def test_toml_merge():
    b = 'name = "x"\n[deps]\na = "1"  # keep\n'
    o = merge_texts(b, b.replace('"1"', '"2"'), b + 'b = "9"\n', "c.toml")
    assert o.clean and 'a = "2"  # keep' in o.text and 'b = "9"' in o.text


def test_ini_merge():
    b = "[s]\na = 1\nb = 2\n"
    o = merge_texts(b, b.replace("a = 1", "a = 5"), b.replace("b = 2", "b = 7"), "c.ini")
    assert o.clean and "a = 5" in o.text and "b = 7" in o.text


def test_env_and_properties():
    b = "A=1\nB=2\n"
    o = merge_texts(b, "A=10\nB=2\n", "A=1\nB=2\nC=3\n", ".env")
    assert o.clean and "A=10" in o.text and "C=3" in o.text
    p = "x.y=1\nz=2\n"
    o = merge_texts(p, "x.y=9\nz=2\n", "x.y=1\nz=2\nq=3\n", "a.properties")
    assert o.clean and "x.y=9" in o.text and "q=3" in o.text


def test_text_list_union_and_unparseable_fallback():
    b = "a\nb\n"
    o = merge_texts(b, "a\nb\nc\n", "a\nb\nd\n", "requirements.txt")
    assert o.clean and set(o.text.split()) == {"a", "b", "c", "d"}
    bad = merge_texts("a: [\n", "a: [1\n", "a: [2\n", "x.yaml")      # not valid YAML
    assert bad.strategy == "textual" and not bad.clean


def test_k8s_multidoc():
    b = "kind: A\nmetadata:\n  name: a\nspec:\n  n: 1\n---\nkind: B\nmetadata:\n  name: b\nspec:\n  n: 1\n"
    ours = b.replace("n: 1\n---", "n: 2\n---")
    theirs = b.rstrip("\n") + "\n" + "---\nkind: C\nmetadata:\n  name: c\n"
    o = merge_texts(b, ours, theirs, "m.yaml")
    assert o.clean and "n: 2" in o.text and "name: c" in o.text and o.text.count("---") >= 2


def test_big_rewrite_defers_to_textual_merge():
    base = "".join(f"k{i}: {i}\n" for i in range(30))
    ours = "".join(f"k{i}: {i + 1000}\n" for i in range(30))        # rewrote everything
    theirs = "".join(f"k{i}: {i + 2000}\n" for i in range(30))      # ... differently, same keys
    o = merge_texts(base, ours, theirs, "x.yaml")
    assert o.strategy == "textual" and not o.clean


def test_normal_sized_edits_are_not_treated_as_rewrite():
    base = "".join(f"k{i}: {i}\n" for i in range(60))
    ours = base.replace("k3: 3", "k3: 30")
    theirs = base.replace("k4: 4", "k4: 40")
    o = merge_texts(base, ours, theirs, "x.yaml")
    assert o.clean and o.strategy == "structured"
