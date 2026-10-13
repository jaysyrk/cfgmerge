"""Learn a merge policy from a file's history (no schema needed).

Learns, per normalised path:
  identity   which field(s) identify items of a list of mappings (stable across versions)
  sorted     lists / maps that are kept sorted
  atomic     mapping subtrees whose fields almost always change together
"""
import subprocess
from collections import Counter, defaultdict

from . import formats as F
from .core_types import ListItem, same
from .identity import infer_key
from .policy import Policy, norm_path

MIN_VOTES = 2
SORTED_RATIO = 0.95
ATOMIC_RATIO = 0.8
ATOMIC_MIN_CHANGES = 5


def _walk(x, path=()):
    yield path, x
    if isinstance(x, dict):
        for k, v in x.items():
            yield from _walk(v, path + (k,))
    elif isinstance(x, list):
        for v in x:
            yield from _walk(v, path + (ListItem("#"),))


def _lists_by_path(data):
    out = defaultdict(list)
    for path, node in _walk(data):
        if isinstance(node, list):
            out[norm_path(path)].append(node)
    return out


def _dicts_by_path(data):
    out = defaultdict(list)
    for path, node in _walk(data):
        if isinstance(node, dict):
            out[norm_path(path)].append(node)
    return out


def _is_sorted(seq):
    try:
        return list(seq) == sorted(seq)
    except TypeError:
        return False


def learn(versions) -> Policy:
    """versions: parsed data, oldest -> newest."""
    versions = [v for v in versions if v is not None]
    pol = Policy()
    if len(versions) < 2:
        return pol
    # ---- identity keys: vote over consecutive version pairs
    votes = defaultdict(Counter)
    for prev, cur in zip(versions, versions[1:]):
        lp, lc = _lists_by_path(prev), _lists_by_path(cur)
        for p in set(lp) & set(lc):
            for a, b in zip(lp[p], lc[p]):
                if a and b and all(isinstance(i, dict) for i in a + b):
                    k = infer_key(a, a, b)
                    if k:
                        votes[p][tuple(".".join(f) for f in k)] += 1
    for p, c in votes.items():
        key, n = c.most_common(1)[0]
        if n >= MIN_VOTES and n / sum(c.values()) >= 0.6:
            pol.identity[p] = list(key)
    # ---- sorted convention
    seen, hit = Counter(), Counter()
    for v in versions:
        for p, lists in _lists_by_path(v).items():
            for l in lists:
                if len(l) >= 3 and all(not isinstance(i, (dict, list)) for i in l):
                    seen[p] += 1
                    hit[p] += _is_sorted(l)
        for p, dicts in _dicts_by_path(v).items():
            for d in dicts:
                if len(d) >= 3 and all(isinstance(k, str) for k in d):
                    seen["{}" + p] += 1
                    hit["{}" + p] += _is_sorted(list(d))
    for p, n in seen.items():
        if n >= 3 and hit[p] / n >= SORTED_RATIO and not p.startswith("{}"):
            pol.sorted.add(p)
    # ---- atomic subtrees (co-change mining)
    changed_any, changed_multi = Counter(), Counter()
    for prev, cur in zip(versions, versions[1:]):
        dp, dc = _dicts_by_path(prev), _dicts_by_path(cur)
        for p in set(dp) & set(dc):
            if p == "":
                continue
            for a, b in zip(dp[p], dc[p]):
                if not (3 <= len(a) <= 12) or a.keys() != b.keys():
                    continue
                diffs = sum(1 for k in a if not same(a[k], b[k]))
                if diffs:
                    changed_any[p] += 1
                    changed_multi[p] += diffs >= 2
    for p, n in changed_any.items():
        if n >= ATOMIC_MIN_CHANGES and changed_multi[p] / n >= ATOMIC_RATIO:
            pol.atomic.add(p)
    return pol


def history(repo, path, rev="HEAD", max_versions=40):
    """File contents at successive revisions, oldest -> newest."""
    r = subprocess.run(["git", "-C", repo, "log", "--format=%H", "-n", str(max_versions), rev, "--", path],
                       capture_output=True, text=True)
    shas = r.stdout.split()
    out = []
    for sha in reversed(shas):
        b = subprocess.run(["git", "-C", repo, "show", f"{sha}:{path}"], capture_output=True)
        if b.returncode == 0:
            try:
                out.append(b.stdout.decode("utf-8"))
            except UnicodeDecodeError:
                pass
    return out


def learn_from_git(repo, path, rev="HEAD", max_versions=40, affinity=False) -> Policy:
    fmt = F.detect(path, "")
    versions = []
    for text in history(repo, path, rev, max_versions):
        try:
            versions.append(F.parse(fmt, text))
        except F.FormatError:
            continue
    pol = learn(versions)
    if affinity:
        pol.affinity = learn_affinity(repo, path, rev)
    return pol


def learn_affinity(repo, path, rev="HEAD", max_merges=60):
    """How were this file's conflicts resolved in past merges? -> {path: {ours,theirs,novel: n}}
    Only merges reachable from `rev` are used (no peeking at the merge being decided)."""
    from .core_types import MISSING
    from .engine import merge_texts
    fmt = F.detect(path, "")
    out = {}
    # enumerate merges ourselves: `git log -- path` prunes merges that equal one parent, which is
    # exactly the merge-forward case we want to learn from
    r = subprocess.run(["git", "-C", repo, "log", "--merges", "--format=%H %P", "-n", "600", rev],
                       capture_output=True, text=True)
    found = 0

    def blob(rev_, p):
        b = subprocess.run(["git", "-C", repo, "show", f"{rev_}:{p}"], capture_output=True)
        return b.stdout.decode("utf-8", "replace") if b.returncode == 0 else None

    def get(d, p):
        cur = d
        for k in p:
            if isinstance(k, ListItem) or not isinstance(cur, dict) or k not in cur:
                return MISSING
            cur = cur[k]
        return cur

    for line in r.stdout.splitlines():
        parts = line.split()
        if len(parts) != 3:
            continue
        m, p1, p2 = parts
        if found >= max_merges:
            break
        ids = subprocess.run(["git", "-C", repo, "rev-parse", f"{p1}:{path}", f"{p2}:{path}"],
                             capture_output=True, text=True)
        sh = ids.stdout.split()
        if ids.returncode != 0 or len(sh) != 2 or sh[0] == sh[1]:
            continue
        found += 1
        mb = subprocess.run(["git", "-C", repo, "merge-base", p1, p2], capture_output=True, text=True).stdout.split()
        if len(mb) != 1:
            continue
        texts = [blob(x, path) for x in (mb[0], p1, p2, m)]
        if any(t is None for t in texts):
            continue
        b, o, t, truth = texts
        try:
            res = merge_texts(b, o, t, path, fmt)
            if res.clean:
                continue
            tp = F.parse(fmt, truth)
        except Exception:
            continue
        for c in res.conflicts:
            if c.kind not in ("value", "delete-modify", "add-add") or any(isinstance(p, ListItem) for p in c.path):
                continue
            tv = get(tp, c.path)
            ch = "ours" if same(tv, c.ours) else "theirs" if same(tv, c.theirs) else "novel"
            d = out.setdefault(norm_path(c.path), {})
            d[ch] = d.get(ch, 0) + 1
    return out
