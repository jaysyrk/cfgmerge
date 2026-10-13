"""Score cfgmerge vs `git merge-file` on mined cases.

For each case the *truth* is what the human committed in the merge. Outcomes:
  correct   clean merge whose parsed tree equals truth
  wrong     clean merge that differs from truth (silently wrong)
  invalid   clean merge that does not even parse
  conflict  needs a human
`unscored` = truth itself does not parse in its format (skipped for both tools).
"""
import argparse
import glob
import hashlib
import json
import os
import subprocess
import sys
import tempfile
from collections import Counter, defaultdict
from concurrent.futures import ProcessPoolExecutor

from .. import formats as F
from ..core_types import canon, same
from ..engine import merge_texts


def repo_split(name: str) -> str:
    """Deterministic dev/held-out split by repo so tuning never sees the test repos."""
    return "dev" if int(hashlib.sha1(name.encode()).hexdigest(), 16) % 2 == 0 else "test"


def git_merge(base, ours, theirs):
    with tempfile.TemporaryDirectory() as d:
        ps = []
        for n, t in (("o", ours), ("b", base), ("t", theirs)):
            p = os.path.join(d, n)
            with open(p, "w") as f:
                f.write(t)
            ps.append(p)
        r = subprocess.run(["git", "merge-file", "-p", *ps], capture_output=True, text=True)
        return r.stdout, r.returncode == 0


def _leaves(x, path=()):
    if isinstance(x, dict):
        for k, v in x.items():
            yield from _leaves(v, path + (str(k),))
    elif isinstance(x, list):
        if not x:
            yield (path + ("[]",), "[]")
        for v in x:
            yield from _leaves(v, path + ("[]",))
    else:
        yield (path, canon(x))


def _leafset(x):
    from ..core_types import MISSING
    return set() if x is MISSING else set(_leaves(x))


def judge(fmt, text, truth_parsed, ctx=None):
    """correct = equals the human result; explained = differs ONLY where the human did extra
    work the three inputs cannot imply (a value found in none of them, or removing something
    both sides kept); wrong = anything else."""
    try:
        got = F.parse(fmt, text)
    except F.FormatError:
        return "invalid"
    if same(got, truth_parsed):
        return "correct"
    if ctx is None:
        return "wrong"
    lb, lo, lt = (_leafset(ctx[k]) for k in ("base", "ours", "theirs"))
    lg, ltr = _leafset(got), _leafset(truth_parsed)
    universe = lb | lo | lt
    explained = True
    novel_paths = {p for p, v in ltr - lg if (p, v) not in universe}
    for leaf in ltr - lg:                       # truth has it, we do not
        if leaf in universe:
            explained = False                   # derivable value we failed to produce
    for leaf in lg - ltr:                       # we have it, truth does not
        if not (leaf in lo and leaf in lt) and leaf[0] not in novel_paths:
            explained = False                   # human rejected a single side's content
    if explained:
        return "explained"
    # Reference "fact algebra" oracle: facts (path,value) both sides kept, plus each side's
    # additions. If we match it, any correct 3-way merge would give our answer and the
    # human simply decided otherwise (e.g. rejecting a side's version bump): "override".
    ref = (lb & lo & lt) | (lo - lb) | (lt - lb)
    per_path = Counter(p for p, _ in ref if "[]" not in p)      # list paths legitimately hold many facts
    if all(n == 1 for n in per_path.values()) and lg == ref:
        return "override"
    return "wrong"


def score_case(case, policy_for=None):
    fmt = case["fmt"]
    try:
        truth = F.parse(fmt, case["truth"])
        ctx = {k: F.parse(fmt, case[k]) for k in ("base", "ours", "theirs")}
    except F.FormatError:
        return None                                   # cannot score semantically
    res = {"repo": case["repo"], "path": case["path"], "fmt": fmt, "merge": case["merge"]}
    gtext, gclean = git_merge(case["base"], case["ours"], case["theirs"])
    res["git"] = judge(fmt, gtext, truth, ctx) if gclean else "conflict"
    pol = policy_for(case) if policy_for else None
    try:
        out = merge_texts(case["base"], case["ours"], case["theirs"], case["path"], fmt,
                          **({"policy": pol} if pol is not None else {}))
        res["cfg"] = judge(fmt, out.text, truth, ctx) if out.clean else "conflict"
        res["strategy"] = out.strategy
        res["ncon"] = len(out.conflicts)
    except Exception as e:                            # a crash is a bug: count it, never hide it
        res["cfg"], res["strategy"], res["err"] = "crash", "crash", f"{type(e).__name__}: {e}"[:200]
    return res


REPO_ROOTS = ["data/repos", "data/repos_test"]


def learned_policy_for(case):
    """Policy learned from the file's history on the ours-side up to (not including) the merge."""
    from ..learn import learn_from_git
    for root in REPO_ROOTS:
        d = os.path.join(root, case["repo"])
        if os.path.isdir(d):
            try:
                return learn_from_git(d, case["path"], rev=case["merge"] + "^1", max_versions=25)
            except Exception:
                return None
    return None


def _run(args):
    path, limit, learn = args
    out = []
    with open(path) as f:
        for i, line in enumerate(f):
            if limit and i >= limit:
                break
            r = score_case(json.loads(line), learned_policy_for if learn else None)
            if r:
                out.append(r)
    return out


def table(rows, title):
    print(f"\n=== {title}  ({len(rows)} cases)")
    print(f"{'':22s}{'correct':>9s}{'explained':>11s}{'override':>10s}{'wrong':>7s}{'invalid':>9s}{'conflict':>10s}{'auto-ok%':>10s}{'wrong%':>8s}")
    print(f"{'git merge-file':22s}" + _fmt(rows, "git"))
    print(f"{'cfgmerge':22s}" + _fmt(rows, "cfg"))


def _fmt(rows, k):
    c = Counter(r[k] for r in rows)
    n = max(1, len(rows))
    ok = c["correct"] + c["explained"] + c["override"]
    return (f"{c['correct']:9d}{c['explained']:11d}{c['override']:10d}{c['wrong']:7d}{c['invalid']:9d}{c['conflict']:10d}"
            f"{100 * ok / n:9.1f}%{100 * (c['wrong'] + c['invalid']) / n:7.1f}%"
            + (f"  crash={c['crash']}" if c["crash"] else ""))


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--cases", default="data/cases")
    ap.add_argument("--split", choices=["dev", "test", "all"], default="all")
    ap.add_argument("--limit", type=int, default=0, help="max cases per repo")
    ap.add_argument("-j", type=int, default=8)
    ap.add_argument("--dump", help="write per-case results as JSONL")
    ap.add_argument("--learn", action="store_true", help="use a policy learned from file history")
    a = ap.parse_args(argv)
    files = sorted(glob.glob(os.path.join(a.cases, "*.jsonl")))
    if a.split != "all":
        files = [f for f in files if repo_split(os.path.basename(f)[:-6]) == a.split]
    rows = []
    with ProcessPoolExecutor(a.j) as ex:
        for r in ex.map(_run, [(f, a.limit, a.learn) for f in files]):
            rows.extend(r)
    table(rows, f"ALL ({a.split})")
    byfmt = defaultdict(list)
    for r in rows:
        byfmt[r["fmt"]].append(r)
    for fmt, rs in sorted(byfmt.items()):
        table(rs, fmt)
    crashes = [r for r in rows if r.get("cfg") == "crash"]
    for r in crashes[:5]:
        print("CRASH", r["repo"], r["path"], r.get("err"))
    if a.dump:
        with open(a.dump, "w") as f:
            for r in rows:
                f.write(json.dumps(r) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
