"""Show why a case differs: semantic diff of cfgmerge output vs the human's result."""
import json
import sys

from .. import formats as F
from ..diff import diff
from ..engine import merge_texts


def load_case(repo, merge, path):
    import os
    for d in ("data/cases", "data/cases_test"):
        p = f"{d}/{repo}.jsonl"
        if not os.path.exists(p):
            continue
        with open(p) as f:
            for line in f:
                c = json.loads(line)
                if c["merge"].startswith(merge) and c["path"] == path:
                    return c


def show(c, maxn=8):
    fmt = c["fmt"]
    out = merge_texts(c["base"], c["ours"], c["theirs"], c["path"], fmt)
    got, truth = F.parse(fmt, out.text), F.parse(fmt, c["truth"])
    print(f"--- {c['repo']} {c['path']} @{c['merge'][:8]} clean={out.clean} strategy={out.strategy}")
    for n in out.notes[:4]:
        print("   note:", n)
    ch = diff(got, truth)
    print(f"   cfgmerge->human differs in {len(ch)} places")
    for x in ch[:maxn]:
        print("   ", x.render())


if __name__ == "__main__":
    rows = [json.loads(l) for l in open(sys.argv[1])]
    sel = [r for r in rows if r["git"] == sys.argv[2] and r["cfg"] == sys.argv[3]]
    if len(sys.argv) > 4:
        sel = [r for r in sel if sys.argv[4] in r["repo"]]
    n = int(sys.argv[5]) if len(sys.argv) > 5 else 6
    for r in sel[:n]:
        show(load_case(r["repo"], r["merge"], r["path"]))
