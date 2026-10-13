"""Three-way merge of sequences with *relaxed adjacency*.

Differences from a line-oriented diff3:
- an insertion that merely touches an edited span (at its boundary) is independent;
- concurrent insertions at the same point are unioned (ours first), not conflicted;
- both sides replacing the same slice with different content is a real conflict.

Elements must be hashable (callers pass identities). Result is a list whose
entries are either elements or `Chunk` conflict markers.
"""
from dataclasses import dataclass
from difflib import SequenceMatcher


@dataclass
class Chunk:
    """An unresolved region: what base/ours/theirs hold for it."""
    base: list
    ours: list
    theirs: list

    @property
    def pairwise(self) -> bool:
        """Equal-length replace on both sides: items can be merged position by position."""
        return len(self.base) == len(self.ours) == len(self.theirs) and len(self.base) > 0


def _spans(base, other):
    sm = SequenceMatcher(None, base, other, autojunk=False)
    return [(i1, i2, j1, j2) for tag, i1, i2, j1, j2 in sm.get_opcodes() if tag != "equal"]


def _overlaps(lo, hi, a, b, strict=False):
    if strict and a <= hi and lo <= b:   # touching counts (git-like)
        return True
    if a < hi and lo < b:
        return True
    if a == b and lo < a < hi:          # insertion strictly inside the cluster
        return True
    if lo == hi and a < lo < b:         # cluster is an insertion inside the span
        return True
    if lo == hi and a == b == lo:       # two insertions at the same point
        return True
    return False


def _apply(base, lo, hi, spans, other):
    out, cur = [], lo
    for i1, i2, j1, j2 in sorted(spans):
        out.extend(base[cur:i1])
        out.extend(other[j1:j2])
        cur = i2
    out.extend(base[cur:hi])
    return out


def merge_sequences(base, ours, theirs, dedupe=True, union=True, strict=False, similar=None):
    base, ours, theirs = list(base), list(ours), list(theirs)
    events = [(s[0], s[1], "o", s) for s in _spans(base, ours)]
    events += [(s[0], s[1], "t", s) for s in _spans(base, theirs)]
    events.sort(key=lambda e: (e[0], e[1], e[2]))
    clusters = []   # [lo, hi, [o spans], [t spans]]
    for a, b, side, span in events:
        if clusters and _overlaps(clusters[-1][0], clusters[-1][1], a, b, strict):
            c = clusters[-1]
            c[0], c[1] = min(c[0], a), max(c[1], b)
        else:
            clusters.append([a, b, [], []])
            c = clusters[-1]
        (c[2] if side == "o" else c[3]).append(span)

    out, pos = [], 0
    for lo, hi, so, st in clusters:
        out.extend(base[pos:lo])
        pos = hi
        r_o = _apply(base, lo, hi, so, ours) if so else base[lo:hi]
        r_t = _apply(base, lo, hi, st, theirs) if st else base[lo:hi]
        slice_b = base[lo:hi]
        if r_o == r_t:
            out.extend(r_o)
        elif r_o == slice_b:
            out.extend(r_t)
        elif r_t == slice_b:
            out.extend(r_o)
        elif lo == hi and union and similar is not None and \
                any(a != b and similar(a, b) for a in r_o for b in r_t):
            out.append(Chunk(slice_b, r_o, r_t))   # same thing added twice, differently: merge/conflict
        elif lo == hi and union:            # concurrent pure insertions: union
            have = set(r_o)
            out.extend(r_o)
            out.extend(x for x in r_t if not (dedupe and x in have))
        else:
            out.append(Chunk(slice_b, r_o, r_t))
    out.extend(base[pos:])
    return out


def flatten(merged, prefer="ours"):
    """Resolve any Chunk by taking one side (used when only an order hint is needed)."""
    out = []
    for x in merged:
        if isinstance(x, Chunk):
            out.extend(x.ours if prefer == "ours" else x.theirs)
        else:
            out.append(x)
    return out
