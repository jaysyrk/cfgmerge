"""For 'wrong' cases: print leaf facts where cfgmerge, the oracle and the human disagree."""
import json
import sys

from .. import formats as F
from ..engine import merge_texts
from .inspect import load_case
from .score import _leafset


def why(r, maxn=6):
    c = load_case(r["repo"], r["merge"], r["path"])
    fmt = c["fmt"]
    b, o, t, tr = (F.parse(fmt, c[k]) for k in ("base", "ours", "theirs", "truth"))
    out = merge_texts(c["base"], c["ours"], c["theirs"], c["path"], fmt)
    got = F.parse(fmt, out.text)
    lb, lo, lt, lg, ltr = (_leafset(x) for x in (b, o, t, got, tr))
    ref = (lb & lo & lt) | (lo - lb) | (lt - lb)
    print(f"== {r['repo']} {r['path']} @{r['merge'][:8]} notes={out.notes[:3]}")
    shown = 0
    for tag, facts in (("cfg-only(vs ref)", lg - ref), ("ref-only(vs cfg)", ref - lg)):
        for p, v in sorted(facts)[:maxn]:
            where = "ours" if (p, v) in lo else ("theirs" if (p, v) in lt else ("base" if (p, v) in lb else "none"))
            inh = "human-has" if (p, v) in ltr else "human-lacks"
            print(f"   {tag}: {'.'.join(p)} = {v[:60]}  [in {where}; {inh}]")
            shown += 1


if __name__ == "__main__":
    rows = [json.loads(l) for l in open(sys.argv[1])]
    sel = [r for r in rows if r["cfg"] == "wrong" and (len(sys.argv) < 3 or sys.argv[2] in (r["fmt"], r["repo"]))]
    start = int(sys.argv[3]) if len(sys.argv) > 3 else 0
    for r in sel[start:start + int(sys.argv[4] if len(sys.argv) > 4 else 6)]:
        why(r)
