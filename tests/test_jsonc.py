import json

import pytest

from cfgmerge import formats as F
from cfgmerge import jsonc
from cfgmerge.core_types import same
from cfgmerge.engine import merge_texts

BASE = '''{
  // compiler options
  "compilerOptions": {
    "target": "es2020", /* keep */
    "strict": true,
  },
  "include": ["src"], // sources
  "exclude": [
    "dist",
    "node_modules"
  ]
}
'''


def test_parses_comments_and_trailing_commas():
    d = F.parse("json", BASE)
    assert d["compilerOptions"]["strict"] is True and d["exclude"] == ["dist", "node_modules"]


def test_patch_preserves_every_comment():
    merged = {"compilerOptions": {"target": "es2022", "strict": True, "noEmit": True},
              "include": ["src", "test"], "exclude": ["dist", "node_modules", "tmp"]}
    out = jsonc.patch(BASE, merged, F._json_style(BASE))
    for c in ("// compiler options", "/* keep */", "// sources"):
        assert c in out
    assert same(F.parse("json", out), merged)
    assert '"target": "es2022"' in out and '"noEmit": true' in out


def test_patch_handles_deletion_and_type_change():
    merged = {"include": "src"}
    out = jsonc.patch(BASE, merged, F._json_style(BASE))
    assert same(F.parse("json", out), merged)


def test_three_way_merge_of_jsonc_keeps_comments():
    ours = BASE.replace('"es2020"', '"es2022"')
    theirs = BASE.replace('"src"', '"src", "lib"').replace('"node_modules"', '"node_modules", "tmp"')
    o = merge_texts(BASE, ours, theirs, "tsconfig.json")
    assert o.clean and o.strategy == "structured"
    assert "// compiler options" in o.text and "/* keep */" in o.text
    d = F.parse("json", o.text)
    assert d["compilerOptions"]["target"] == "es2022" and "lib" in d["include"] and "tmp" in d["exclude"]


def test_conflict_in_jsonc_is_reported():
    ours = BASE.replace('"es2020"', '"es2022"')
    theirs = BASE.replace('"es2020"', '"esnext"')
    o = merge_texts(BASE, ours, theirs, "tsconfig.json")
    assert not o.clean and o.conflicts[0].where() == "compilerOptions.target"


def test_empty_containers_and_new_keys():
    base = '{\n  // none yet\n  "a": {},\n  "b": []\n}\n'
    merged = {"a": {"x": 1}, "b": [1, 2]}
    out = jsonc.patch(base, merged, F._json_style(base))
    assert "// none yet" in out and same(F.parse("json", out), merged)


def test_errors_are_format_errors_not_crashes():
    with pytest.raises(F.FormatError):
        F.parse("json", '{"a": }')
