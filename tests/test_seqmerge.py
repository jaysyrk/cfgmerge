from cfgmerge.seqmerge import Chunk, merge_sequences, flatten


def m(b, o, t):
    return merge_sequences(b, o, t)


def test_concurrent_appends_union():
    assert m("abc", "abcd", "abce") == list("abcde")


def test_edit_next_to_insert_is_independent():
    # ours deletes b, theirs inserts x right after b
    assert m("abc", "ac", "abxc") == list("axc")


def test_same_change_both_sides():
    assert m("abc", "ac", "ac") == list("ac")


def test_replace_same_slot_differently_conflicts():
    r = m("abc", "ayc", "azc")
    assert len(r) == 3 and isinstance(r[1], Chunk)
    assert r[1].ours == ["y"] and r[1].theirs == ["z"] and r[1].pairwise


def test_one_side_only():
    assert m("abc", "abc", "xabc") == list("xabc")


def test_insert_inside_deleted_span_conflicts():
    r = m("abcd", "ad", "abxcd")        # ours drops b,c ; theirs inserts x between them
    assert any(isinstance(x, Chunk) for x in r)


def test_flatten_prefers_side():
    r = m("abc", "ayc", "azc")
    assert flatten(r) == list("ayc") and flatten(r, "theirs") == list("azc")


def test_independent_edits_far_apart():
    assert m("abcdefg", "aXcdefg", "abcdefY") == list("aXcdefY")
