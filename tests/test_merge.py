from cfgmerge.merge import merge, ConflictRef


def clean(r):
    assert not r.conflicts, [c.where() for c in r.conflicts]
    return r.merged


def test_disjoint_map_edits():
    b = {"a": 1, "b": 2, "c": {"x": 1}}
    assert clean(merge(b, {**b, "a": 9}, {**b, "c": {"x": 5}})) == {"a": 9, "b": 2, "c": {"x": 5}}


def test_scalar_conflict():
    r = merge({"a": 1}, {"a": 2}, {"a": 3})
    assert len(r.conflicts) == 1 and r.conflicts[0].kind == "value"
    assert isinstance(r.merged["a"], ConflictRef)


def test_delete_modify_conflict():
    r = merge({"a": 1, "b": 2}, {"b": 2}, {"a": 5, "b": 2})
    assert r.conflicts[0].kind == "delete-modify"


def test_concurrent_list_appends_union_keyed():
    b = {"items": [{"name": "a", "v": 1}]}
    o = {"items": [{"name": "a", "v": 1}, {"name": "b", "v": 2}]}
    t = {"items": [{"name": "a", "v": 1}, {"name": "c", "v": 3}]}
    got = clean(merge(b, o, t))["items"]
    assert [i["name"] for i in got] == ["a", "b", "c"]


def test_keyed_item_edit_merges_fields():
    b = {"s": [{"name": "web", "port": 80, "tag": "1"}, {"name": "db", "port": 5}]}
    o = {"s": [{"name": "web", "port": 81, "tag": "1"}, {"name": "db", "port": 5}]}
    t = {"s": [{"name": "web", "port": 80, "tag": "2"}, {"name": "db", "port": 5}]}
    got = clean(merge(b, o, t))["s"]
    assert got[0] == {"name": "web", "port": 81, "tag": "2"}


def test_scalar_list_union_and_independent_edit():
    b = {"l": ["a", "b", "c"]}
    assert clean(merge(b, {"l": ["a", "b", "c", "d"]}, {"l": ["a", "b", "c", "e"]}))["l"] == ["a", "b", "c", "d", "e"]
    assert clean(merge(b, {"l": ["a", "c"]}, {"l": ["a", "b", "x", "c"]}))["l"] == ["a", "x", "c"]


def test_same_slot_double_edit_conflicts():
    b = {"l": ["a", "b", "c"]}
    r = merge(b, {"l": ["a", "y", "c"]}, {"l": ["a", "z", "c"]})
    assert r.conflicts and r.conflicts[0].kind == "value"      # pairwise -> scalar conflict


def test_rename_forwards_edit():
    b = {"old": {"x": 1, "y": 2}}
    o = {"new": {"x": 1, "y": 2}}
    t = {"old": {"x": 1, "y": 9}}
    assert clean(merge(b, o, t)) == {"new": {"x": 1, "y": 9}}


def test_equivalent_values_dont_conflict():
    r = merge({"t": "30s"}, {"t": "30s "}, {"t": "30 sec"})
    assert not r.conflicts


def test_add_add_maps_merge_recursively():
    r = merge({}, {"a": {"x": 1}}, {"a": {"y": 2}})
    assert clean(r) == {"a": {"x": 1, "y": 2}}


def test_sorted_convention_kept():
    b = {"k": ["a", "c", "e"]}
    got = clean(merge(b, {"k": ["a", "b", "c", "e"]}, {"k": ["a", "c", "d", "e"]}))["k"]
    assert got == ["a", "b", "c", "d", "e"]


def test_same_item_added_twice_differently_conflicts_not_duplicates():
    b = {"steps": [{"uses": "x"}, {"uses": "x"}]}              # duplicates: no usable identity key
    o = {"steps": [{"uses": "x"}, {"uses": "x"}, {"name": "T", "run": "cargo test --x", "dir": "u"}]}
    t = {"steps": [{"uses": "x"}, {"uses": "x"}, {"name": "T", "run": "cargo test --y", "dir": "u"}]}
    r = merge(b, o, t)
    assert len(r.conflicts) == 1 and r.conflicts[0].kind == "add-add"
    assert len(r.merged["steps"]) == 3                      # one merged item, not two copies


def test_unrelated_concurrent_inserts_still_union():
    b = {"steps": [{"uses": "x"}, {"uses": "x"}]}
    o = {"steps": [{"uses": "x"}, {"uses": "x"}, {"name": "X", "run": "x"}]}
    t = {"steps": [{"uses": "x"}, {"uses": "x"}, {"name": "Y", "run": "y"}]}
    r = merge(b, o, t)
    assert not r.conflicts and len(r.merged["steps"]) == 4
