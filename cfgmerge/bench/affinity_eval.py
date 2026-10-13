"""Does 'learn how past merges resolved this path' predict future resolutions?

Strict temporal protocol: cases are mined newest-first, so for a case at position i the only
allowed evidence is cases i+1.. of the same repo+file (older merges). A prediction is made
only when the policy would actually auto-apply (>= MIN_N older observations, >= MIN_RATIO agree).
"""
import glob
import json
import os
import sys
from collections import Counter, defaultdict

from .. import formats as F
from ..core_types import MISSING, ListItem, same
from ..engine import merge_texts
from ..policy import norm_path

MIN_N, MIN_RATIO = 5, 0.95


def _get(d, path):
    cur = d
    for p in path:
        if isinstance(p, ListItem) or not isinstance(cur, dict) or p not in cur:
            return MISSING
        cur = cur[p]
    return cur


def collect(dirs):
    ev = defaultdict(list)           # (repo, file, path) -> [(order, choice)]
    for d in dirs:
        for f in sorted(glob.glob(os.path.join(d, "*.jsonl"))):
            for order, line in enumerate(open(f)):
                c = json.loads(line)
                try:
                    out = merge_texts(c["base"], c["ours"], c["theirs"], c["path"], c["fmt"])
                    if out.clean:
                        continue
                    truth = F.parse(c["fmt"], c["truth"])
                except Exception:
                    continue
                for cf in out.conflicts:
                    if cf.kind not in ("value", "delete-modify", "add-add") or \
                            any(isinstance(p, ListItem) for p in cf.path):
                        continue
                    tv = _get(truth, cf.path)
                    ch = "ours" if same(tv, cf.ours) else "theirs" if same(tv, cf.theirs) else "novel"
                    ev[(c["repo"], c["path"], norm_path(cf.path))].append((order, ch))
    return ev


def evaluate(ev):
    per_repo = defaultdict(lambda: [0, 0, 0])      # predictions, correct, conflicts seen
    for (repo, _file, _p), evs in ev.items():
        evs.sort()                                 # ascending order = newest first
        for i, (_o, ch) in enumerate(evs):
            per_repo[repo][2] += 1
            older = [c for _, c in evs[i + 1:]]
            if len(older) < MIN_N:
                continue
            maj, n = Counter(older).most_common(1)[0]
            if maj != "novel" and n / len(older) >= MIN_RATIO:
                per_repo[repo][0] += 1
                per_repo[repo][1] += (maj == ch)
    return per_repo


def main():
    dirs = sys.argv[1:] or ["data/cases", "data/cases_test"]
    per = evaluate(collect(dirs))
    tp = sum(v[0] for v in per.values())
    tc = sum(v[1] for v in per.values())
    ts = sum(v[2] for v in per.values())
    print(f"conflicts seen: {ts}   auto-applicable predictions: {tp}   correct: {tc}   "
          f"precision: {100 * tc / max(1, tp):.1f}%   coverage: {100 * tp / max(1, ts):.1f}%")
    print(f"{'repo':45s} {'pred':>5s} {'ok':>4s} {'prec':>6s} {'conflicts':>10s}")
    for r, (p, c, s) in sorted(per.items(), key=lambda kv: -kv[1][0]):
        if p:
            print(f"{r:45s} {p:5d} {c:4d} {100 * c / p:5.0f}% {s:10d}")
    rest = sum(1 for v in per.values() if v[0] == 0)
    print(f"({rest} repos produced no confident prediction)")


if __name__ == "__main__":
    main()
