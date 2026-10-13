"""Schema-free inference of "what identifies an item" in a list of mappings."""
from .core_types import MISSING, canon

PRIORS = ["name", "id", "key", "path", "hostname", "host", "hosts", "image", "containerPort", "port",
          "mountPath", "address", "url", "title", "label", "alias", "event", "class", "type", "kind",
          "target", "source", "from", "to", "topic", "group", "artifactId", "groupId", "src", "dest",
          "job", "role", "rule", "match", "ip", "interface", "device", "service", "namespace", "user"]
_RANK = {n: i for i, n in enumerate(PRIORS)}


def get_path(item, path):
    cur = item
    for p in path:
        if isinstance(cur, dict) and p in cur:
            cur = cur[p]
        else:
            return MISSING
    if isinstance(cur, list) and len(cur) == 1 and not isinstance(cur[0], (dict, list)):
        return cur[0]                         # XML-style single-value wrapper
    return cur


def _scalar_ok(v):
    return v is not MISSING and v is not None and not isinstance(v, (dict, list)) and v != ""


def _dicts(items):
    return [it for it in items if isinstance(it, dict)]


def _candidates(items_per_version):
    """Field paths (depth<=2) holding a scalar in >= 75% of the mapping items of every version."""
    paths = {}
    for items in items_per_version:
        ds = _dicts(items)
        for it in ds:
            for k, v in it.items():
                if isinstance(v, dict):
                    for k2, v2 in v.items():
                        if _scalar_ok(v2):
                            paths.setdefault((k, k2), set())
                elif _scalar_ok(v):
                    paths.setdefault((k,), set())
    out = []
    for p in sorted(paths):
        ok = True
        for items in items_per_version:
            ds = _dicts(items)
            if not ds:
                continue
            have = sum(1 for it in ds if _scalar_ok(get_path(it, p)))
            if have / len(ds) < 0.75:
                ok = False
                break
        if ok:
            out.append(p)
    return out


def _tuple_of(it, path_t):
    return tuple(canon(get_path(it, p)) for p in path_t)


def _unique(path_t, items):
    seen = set()
    for it in items:
        if not isinstance(it, dict):
            continue
        v = _tuple_of(it, path_t)
        if v in seen:
            return False
        seen.add(v)
    return True


def _full_cover(path, items):
    return all(_scalar_ok(get_path(it, path)) for it in items if isinstance(it, dict))


def infer_key(base, ours, theirs):
    """-> tuple of field paths, or None when items have no usable identity."""
    versions = [v for v in (base, ours, theirs) if isinstance(v, list)]
    if not versions or not any(versions):
        return None
    nonempty = [v for v in versions if v]
    n_items = sum(len(v) for v in nonempty)
    n_dicts = sum(len(_dicts(v)) for v in nonempty)
    if n_dicts == 0 or n_dicts / n_items < 0.8:
        return None
    cands = _candidates(nonempty)
    singles = [c for c in cands if all(_full_cover(c, v) for v in nonempty)
               and all(_unique((c,), v) for v in nonempty)]
    if singles:
        def overlap(path):
            if not isinstance(base, list) or not base:
                return 0.5
            bs = {canon(get_path(i, path)) for i in base if isinstance(i, dict)}
            hits = n = 0
            for other in (ours, theirs):
                if isinstance(other, list):
                    os_ = {canon(get_path(i, path)) for i in other if isinstance(i, dict)}
                    hits += len(bs & os_)
                    n += len(bs)
            return hits / n if n else 0.5

        def score(path):
            pr = _RANK.get(path[-1], 99) if len(path) == 1 else (
                _RANK.get(path[-1], 99) + 20 if path[0] == "metadata" else 120)
            return (-overlap(path), pr, len(path), path)
        best = min(singles, key=score)
        if len(nonempty) > 1 and n_items > 3 and overlap(best) == 0 and isinstance(base, list) and base:
            return None
        return (best,)
    return _composite(nonempty, cands)


def _composite(versions, cands):
    from itertools import combinations
    top = sorted(cands, key=lambda p: (_RANK.get(p[-1], 99), p))[:7]
    for r in (2, 3):
        for combo in combinations(top, r):
            if all(_unique(combo, v) for v in versions):
                return combo
    return None


def ident(item, key):
    if not isinstance(item, dict):
        return ("#", canon(item))
    return tuple(canon(get_path(item, p)) for p in key)
