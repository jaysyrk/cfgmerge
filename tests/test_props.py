import json

from hypothesis import HealthCheck, given, settings, strategies as st

from cfgmerge import formats as F
from cfgmerge.core_types import same
from cfgmerge.engine import merge_texts
from cfgmerge.merge import merge

scalars = st.one_of(st.none(), st.booleans(), st.integers(-5, 5),
                    st.text(alphabet="abcxyz", min_size=0, max_size=4))
keys = st.text(alphabet="abcde", min_size=1, max_size=2)
data = st.recursive(
    scalars,
    lambda c: st.one_of(st.lists(c, max_size=4), st.dictionaries(keys, c, max_size=4)),
    max_leaves=12)
docs = st.dictionaries(keys, data, min_size=1, max_size=4)
S = settings(max_examples=150, deadline=None, suppress_health_check=[HealthCheck.too_slow])


@S
@given(docs, docs)
def test_identity_laws(b, o):
    assert same(merge(b, o, b).merged, o)
    assert same(merge(b, b, o).merged, o)
    assert same(merge(b, o, o).merged, o)


@S
@given(docs, docs, docs)
def test_no_crash_and_conflicts_reported(b, o, t):
    r = merge(b, o, t)
    # either clean (tree has no placeholders) or conflicts are listed
    from cfgmerge.merge import ConflictRef

    def has_ref(x):
        if isinstance(x, ConflictRef):
            return True
        if isinstance(x, dict):
            return any(has_ref(v) for v in x.values())
        if isinstance(x, list):
            return any(has_ref(v) for v in x)
        return False
    assert has_ref(r.merged) == bool(r.conflicts)


@S
@given(docs, docs, docs)
def test_clean_json_output_parses_and_matches(b, o, t):
    tb, to, tt = (json.dumps(x, indent=2) + "\n" for x in (b, o, t))
    out = merge_texts(tb, to, tt, "x.json")
    if out.clean:
        got = F.parse("json", out.text)
        assert same(got, merge(b, o, t).merged)


@S
@given(docs)
def test_json_render_roundtrip(d):
    text = F.render("json", d, json.dumps(d, indent=4) + "\n")
    assert same(F.parse("json", text), d)
