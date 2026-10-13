"""Benchmark on templated YAML (Helm/Go-template/Jinja) merges that do not parse as YAML.

There is no tree to compare, so judging is textual:
  exact      result text == what the human committed (trailing whitespace ignored)
  reference  same multiset of lines as the ideal line-fact merge (B&O&T)+(O-B)+(T-B): the human
             did something else (order, extra edit) but nothing was lost or invented
  wrong      clean, but neither of the above
  broken     clean and template blocks are unbalanced (if/end) - a hard error
  conflict   needs a human
"""
import argparse
import glob
import json
import os
import re
import sys
from collections import Counter
from concurrent.futures import ProcessPoolExecutor

from .. import formats as F
from .. import template as T
from ..engine import merge_texts
from .score import git_merge

TPL = re.compile(r"\{\{|\{%")


def _norm(text):
    return [l.rstrip() for l in text.rstrip("\n").split("\n")]


def _lines(text):
    return Counter(l.strip() for l in text.split("\n") if l.strip())


def judge(text, case):
    if _norm(text) == _norm(case["truth"]):
        return "exact"
    b, o, t = (_lines(case[k]) for k in ("base", "ours", "theirs"))
    ref = (b & o & t) + ((o - b) | (t - b))
    if _lines(text) == ref:
        return "reference"
    bal = T.balance(text)
    if bal is None or bal != 0 and T.balance(case["ours"]) == 0:
        return "broken"
    return "wrong"


def is_case(c):
    if c["fmt"] != "yaml":
        return False
    texts = [c[k] for k in ("base", "ours", "theirs", "truth")]
    if not any(TPL.search(x) for x in texts):
        return False
    try:
        for x in texts[:3]:
            F.parse("yaml", x)
        return False
    except F.FormatError:
        return True


def run(path):
    out = []
    for line in open(path):
        c = json.loads(line)
        if not is_case(c):
            continue
        gt, gok = git_merge(c["base"], c["ours"], c["theirs"])
        o = merge_texts(c["base"], c["ours"], c["theirs"], c["path"], "yaml")
        out.append({"repo": c["repo"], "path": c["path"], "merge": c["merge"],
                    "git": judge(gt, c) if gok else "conflict",
                    "cfg": judge(o.text, c) if o.clean else "conflict",
                    "strategy": o.strategy})
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cases", nargs="+", default=["data/cases", "data/cases_test"])
    ap.add_argument("--dump")
    a = ap.parse_args()
    files = [f for d in a.cases for f in sorted(glob.glob(os.path.join(d, "*.jsonl")))]
    rows = []
    with ProcessPoolExecutor(8) as ex:
        for r in ex.map(run, files):
            rows.extend(r)
    n = len(rows)
    print(f"templated, unparseable-as-YAML merge cases: {n}   repos: {len({r['repo'] for r in rows})}")
    cols = ["exact", "reference", "wrong", "broken", "conflict"]
    print(f"{'':16s}" + "".join(f"{c:>11s}" for c in cols) + f"{'auto-ok%':>10s}{'bad%':>7s}")
    for name, k in (("git merge-file", "git"), ("cfgmerge", "cfg")):
        c = Counter(r[k] for r in rows)
        ok = c["exact"] + c["reference"]
        print(f"{name:16s}" + "".join(f"{c[x]:11d}" for x in cols)
              + f"{100 * ok / max(1, n):9.1f}%{100 * (c['wrong'] + c['broken']) / max(1, n):6.1f}%")
    good = {"exact", "reference"}
    cross = Counter(("ok" if r["git"] in good else r["git"], "ok" if r["cfg"] in good else r["cfg"]) for r in rows)
    print("\ngit x cfgmerge:", dict(cross))
    print("strategies used:", dict(Counter(r["strategy"] for r in rows)))
    if a.dump:
        with open(a.dump, "w") as f:
            for r in rows:
                f.write(json.dumps(r) + "\n")


if __name__ == "__main__":
    sys.exit(main())
