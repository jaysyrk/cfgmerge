"""Three-way semantic merge on plain data trees.

merge = identity resolution + per-identity fact merge:
  maps  -> keys are identities
  lists -> inferred/learned identity key, else content identity (set-like with
           position-aware sequence merge)
Conflicts are node-granular and left in the tree as `ConflictRef` placeholders.
"""
from dataclasses import dataclass, field

from .core_types import MISSING, ListItem, canon, same
from .equiv import equivalent
from .formats import Lines, MultiDoc
from .identity import ident, infer_key
from .policy import EMPTY, Policy
from .seqmerge import Chunk, flatten, merge_sequences

M = MISSING


class ConflictRef:
    __slots__ = ("index",)

    def __init__(self, index):
        self.index = index

    def __repr__(self):
        return f"<conflict {self.index}>"


@dataclass
class Conflict:
    index: int
    path: tuple
    kind: str          # value | add-add | delete-modify | atomic | list | type
    base: object
    ours: object
    theirs: object
    note: str = ""
    suggestion: str = ""          # "ours" | "theirs" learned from past merges of this file
    confidence: float = 0.0

    def where(self):
        from .policy import norm_path
        return norm_path(self.path) or "<root>"


@dataclass
class Result:
    merged: object
    conflicts: list = field(default_factory=list)
    notes: list = field(default_factory=list)       # (kind, path-string)


def _leaves(x, prefix=()):
    if isinstance(x, dict):
        for k, v in x.items():
            yield from _leaves(v, prefix + (str(k),))
    elif isinstance(x, list):
        for i, v in enumerate(x):
            yield from _leaves(v, prefix + (f"[{i}]",))
    else:
        yield (prefix, canon(x))


def _similar(a, b) -> bool:
    """Rename evidence. Scalars never count (version strings and flags repeat all over a
    config); containers need >= 2 shared leaves and >= 60% overlap."""
    if isinstance(a, dict) and isinstance(b, dict) or isinstance(a, list) and isinstance(b, list):
        la, lb = set(_leaves(a)), set(_leaves(b))
        if len(la) < 2 or len(lb) < 2:
            return False
        return len(la & lb) / len(la | lb) >= 0.6
    return False


def _sorted_like(keys):
    try:
        return len(keys) >= 3 and list(keys) == sorted(keys)
    except TypeError:
        return False


class Merger:
    def __init__(self, policy: Policy = EMPTY, text_union: bool = False):
        self.policy = policy
        self.text_union = text_union
        self.conflicts = []
        self.notes = []

    # ------------------------------------------------------------ helpers
    def _conflict(self, path, kind, b, o, t, note=""):
        c = Conflict(len(self.conflicts), tuple(path), kind, b, o, t, note)
        self.conflicts.append(c)
        return ConflictRef(c.index)

    def _note(self, kind, path):
        from .policy import norm_path
        self.notes.append((kind, norm_path(path)))

    # ------------------------------------------------------------ dispatch
    def merge3(self, path, b, o, t):
        if same(o, t):
            return o
        if same(o, b):
            return t
        if same(t, b):
            return o
        if self.policy.is_atomic(path):
            return self._conflict(path, "atomic", b, o, t, "subtree changes together (learned/declared)")
        if isinstance(o, dict) and isinstance(t, dict):
            return self.merge_map(path, b if isinstance(b, dict) else {}, o, t)
        if isinstance(o, list) and isinstance(t, list):
            res = self.merge_list(path, b if isinstance(b, list) else [], o, t)
            if isinstance(o, MultiDoc) or isinstance(t, MultiDoc):
                res = MultiDoc(res)
            elif isinstance(o, Lines) or isinstance(t, Lines):
                res = Lines(res)
            return res
        if isinstance(o, str) and isinstance(t, str) and isinstance(b, str):
            if "\n" in o or "\n" in t or "\n" in b:
                return self._merge_text(path, b, o, t)
            if len(b) >= 40 and " " in b:
                return self._merge_tokens(path, b, o, t)
        if o is not M and t is not M and equivalent(o, t):
            self._note("equivalent", path)
            return o
        kind = "add-add" if b is M else ("type" if type(o) is not type(t) else "value")
        return self._conflict(path, kind, b, o, t)

    def _merge_text(self, path, b, o, t):
        """Multi-line string (an embedded config, a regex block...): strict line merge like git."""
        lb, lo, lt = b.split("\n"), o.split("\n"), t.split("\n")
        merged = merge_sequences(lb, lo, lt, dedupe=False, union=False, strict=True)
        if any(isinstance(x, Chunk) for x in merged):
            return self._conflict(path, "value", b, o, t, "multi-line text edited on both sides")
        self._note("text-merge", path)
        return "\n".join(merged)

    def _merge_tokens(self, path, b, o, t):
        """Long single-line string (a folded scalar, a command line): strict word-level merge, so
        edits in different words merge but edits to the same or neighbouring words conflict."""
        import re
        tok = lambda s: re.split(r"(\s+)", s)
        merged = merge_sequences(tok(b), tok(o), tok(t), dedupe=False, union=False, strict=True)
        if any(isinstance(x, Chunk) for x in merged):
            return self._conflict(path, "value", b, o, t)
        self._note("token-merge", path)
        return "".join(merged)

    # ------------------------------------------------------------ members (maps + keyed lists)
    def _resolve_member(self, path, b, o, t):
        """-> value, or M meaning "dropped"."""
        if o is M and t is M:
            return M
        if b is M:
            if o is M:
                return t
            if t is M:
                return o
            return self.merge3(path, M, o, t)
        if o is M:
            if same(t, b):
                return M
            return self._conflict(path, "delete-modify", b, M, t, "deleted on ours, modified on theirs")
        if t is M:
            if same(o, b):
                return M
            return self._conflict(path, "delete-modify", b, o, M, "modified on ours, deleted on theirs")
        return self.merge3(path, b, o, t)

    # ------------------------------------------------------------ maps
    def _renames(self, base, side, other):
        removed = [k for k in base if k not in side]
        added = [k for k in side if k not in base]
        out = {}
        for k in removed:
            if k in other and not same(other[k], base[k]):
                cands = [a for a in added if _similar(side[a], base[k]) and a not in out.values()]
                if len(cands) == 1:
                    out[k] = cands[0]
        return out

    def merge_map(self, path, b, o, t):
        ren_o = self._renames(b, o, t)
        ren_t = self._renames(b, t, o)
        for k in set(ren_o) & set(ren_t):
            if ren_o[k] != ren_t[k]:
                ren_o.pop(k), ren_t.pop(k)          # both renamed differently: let normal logic conflict
        if ren_o or ren_t:
            def rename(d, r):
                return {r.get(k, k): v for k, v in d.items()}
            for r in (ren_o, ren_t):
                if r:
                    b, o, t = rename(b, r), rename(o, r) if r is ren_t else o, rename(t, r) if r is ren_o else t
                    self._note("rename", path + (",".join(r.values()),))
            # after renaming base on both, ours must carry ours-renames (already named) and
            # theirs its own; keys of the other side were forwarded above.
        order = flatten(merge_sequences(list(b), list(o), list(t)))
        seen = set(order)
        for src in (o, t, b):
            for k in src:
                if k not in seen:
                    order.append(k)
                    seen.add(k)
        out = {}
        for k in order:
            v = self._resolve_member(path + (k,), b.get(k, M), o.get(k, M), t.get(k, M))
            if v is not M:
                out[k] = v
        if _sorted_like(list(o)) and _sorted_like(list(t)) and list(out) != sorted(out):
            try:
                out = {k: out[k] for k in sorted(out)}
                self._note("sorted", path)
            except TypeError:
                pass
        return out

    # ------------------------------------------------------------ lists
    @staticmethod
    def _corresponds(bi, oi, ti):
        """Positional pairing inside an equal-length replaced region is trusted when the three
        items are recognisably the same thing: same container kind and either similar field
        names or enough shared leaves."""
        if not any(isinstance(x, (dict, list)) for x in (bi, oi, ti)):
            return True
        if not (type(bi) is type(oi) is type(ti)):
            return False
        if isinstance(bi, list):
            return True
        kb = set(bi)
        for other in (oi, ti):
            ko = set(other)
            if kb and ko and len(kb & ko) / len(kb | ko) >= 0.5:
                continue
            lb, lo = set(_leaves(bi)), set(_leaves(other))
            if lb and lo and len(lb & lo) / len(lb | lo) >= 0.4:
                continue
            return False
        return True

    def merge_list(self, path, b, o, t):
        if len(b) == len(o) == len(t) == 1 and all(isinstance(v[0], dict) for v in (b, o, t)):
            return [self.merge3(path + (ListItem("#"),), b[0], o[0], t[0])]      # XML-style wrapper
        key = self.policy.identity_for(path)
        if key is None and not self.policy.is_ordered(path):
            key = infer_key(b, o, t)
        if key:
            ok = True
            try:
                maps = [self._id_map(v, key) for v in (b, o, t)]
                ok = all(len(m) == len(v) for m, v in zip(maps, (b, o, t)))
            except Exception:
                ok = False
            if ok:
                return self._merge_keyed(path, b, o, t, key, maps)
        return self._merge_atoms(path, b, o, t)

    @staticmethod
    def _id_map(items, key):
        """identity -> item; non-mapping items get an occurrence counter so None/dupes survive."""
        out, count = {}, {}
        for it in items:
            i = ident(it, key)
            if i and i[0] == "#":
                n = count.get(i, 0)
                count[i] = n + 1
                i = i + (n,)
            out[i] = it
        return out

    @staticmethod
    def _key_leaves(item, key):
        kf = {tuple(k) for k in key}
        out = set()
        for p, v in _leaves(item):
            # drop leaves that sit on a key field
            if tuple(x for x in p) in kf:
                continue
            out.add((p, v))
        return out

    def _id_renames(self, bm, sm, other, key):
        """Items whose identity field was edited on side `sm` while `other` deleted/modified the
        original: map old id -> new id so the two edits meet instead of passing silently."""
        removed = [k for k in bm if k not in sm]
        added = [k for k in sm if k not in bm]
        out, taken = {}, set()
        for k in removed:
            ob = other.get(k, M)
            if ob is not M and same(ob, bm[k]):
                continue                      # other side untouched: plain replace is right
            lb = self._key_leaves(bm[k], key)
            if len(lb) < 1:
                continue
            cands = []
            for a in added:
                if a in taken or a in other:
                    continue
                la = self._key_leaves(sm[a], key)
                shared = len(lb & la)
                if shared >= 1 and shared / len(lb) >= 0.5:
                    cands.append(a)
            if len(cands) == 1:
                out[k] = cands[0]
                taken.add(cands[0])
        return out

    @staticmethod
    def _double_adds(bm, om, tm):
        """Items both sides added under different identities but that are clearly the same
        thing (>= 2 shared leaves and >= 50% overlap): map theirs' id onto ours."""
        add_o = [k for k in om if k not in bm and k not in tm]
        add_t = [k for k in tm if k not in bm and k not in om]
        out, used = {}, set()
        for ko in add_o:
            lo = set(_leaves(om[ko]))
            best = [kt for kt in add_t if kt not in used
                    and len(lo & set(_leaves(tm[kt]))) >= 2
                    and len(lo & set(_leaves(tm[kt]))) / len(lo | set(_leaves(tm[kt]))) >= 0.5]
            if len(best) == 1:
                out[best[0]] = ko
                used.add(best[0])
        return out

    @staticmethod
    def _remap(m, ren):
        return {ren.get(k, k): v for k, v in m.items()}

    def _merge_keyed(self, path, b, o, t, key, maps):
        bm, om, tm = maps
        r_o = self._id_renames(bm, om, tm, key)
        r_t = self._id_renames(bm, tm, om, key)
        for k in set(r_o) & set(r_t):
            r_o.pop(k, None), r_t.pop(k, None)
        if r_o:
            bm, tm = self._remap(bm, r_o), self._remap(tm, r_o)
            self._note("id-rename", path)
        if r_t:
            bm, om = self._remap(bm, r_t), self._remap(om, r_t)
            self._note("id-rename", path)
        dbl = self._double_adds(bm, om, tm)
        if dbl:
            tm = self._remap(tm, dbl)
            self._note("double-add", path)
        order = flatten(merge_sequences(list(bm), list(om), list(tm)))
        seen = set(order)
        for src in (om, tm, bm):
            for k in src:
                if k not in seen:
                    order.append(k)
                    seen.add(k)
        out = []
        for k in order:
            label = ListItem(" ".join(str(x).strip('"') for x in k))
            v = self._resolve_member(path + (label,), bm.get(k, M), om.get(k, M), tm.get(k, M))
            if v is not M:
                out.append(v)
        if _sorted_like(list(om)) and _sorted_like(list(tm)):
            try:
                keyf = lambda it: ident(it, key) if isinstance(it, dict) else ()
                if all(isinstance(x, dict) for x in out):
                    out.sort(key=keyf)
                    self._note("sorted", path)
            except TypeError:
                pass
        return out

    def _merge_atoms(self, path, b, o, t):
        cb, co, ct = ([canon(x) for x in v] for v in (b, o, t))
        lookup = {}
        for v, c in ((b, cb), (o, co), (t, ct)):
            for item, cn in zip(v, c):
                lookup.setdefault(cn, item)
        unique = all(len(set(c)) == len(c) for c in (cb, co, ct))
        union = self.text_union or not isinstance(o, Lines)

        def similar(a, b):
            ia, ib = lookup[a], lookup[b]
            if not (isinstance(ia, dict) and isinstance(ib, dict)):
                return False
            la, lb = set(_leaves(ia)), set(_leaves(ib))
            return len(la & lb) >= 2 and len(la & lb) / len(la | lb) >= 0.5

        merged = merge_sequences(cb, co, ct, dedupe=unique, union=union, similar=similar)
        out = []
        for x in merged:
            if isinstance(x, Chunk) and not x.base:
                # concurrent inserts: pair near-duplicates, keep the rest (ours first, then theirs)
                used = set()
                for oi in x.ours:
                    match = next((ti for ti in x.theirs if ti not in used and ti != oi and similar(oi, ti)), None)
                    if match is not None:
                        used.add(match)
                        out.append(self.merge3(path + (ListItem("#"),), M, lookup[oi], lookup[match]))
                    else:
                        out.append(lookup[oi])
                have = set(x.ours)
                out.extend(lookup[ti] for ti in x.theirs if ti not in used and ti not in have)
            elif isinstance(x, Chunk):
                if x.pairwise and all(self._corresponds(lookup[bi], lookup[oi], lookup[ti])
                                      for bi, oi, ti in zip(x.base, x.ours, x.theirs)):
                    for bi, oi, ti in zip(x.base, x.ours, x.theirs):
                        out.append(self.merge3(path + (ListItem("#"),), lookup[bi], lookup[oi], lookup[ti]))
                else:
                    out.append(self._conflict(
                        path, "list", [lookup[i] for i in x.base], [lookup[i] for i in x.ours],
                        [lookup[i] for i in x.theirs], "both sides changed the same list region differently"))
            else:
                out.append(lookup[x])
        if unique and _sorted_like(co) and _sorted_like(ct) and not any(isinstance(v, ConflictRef) for v in out):
            try:
                out.sort(key=canon if any(isinstance(v, (dict, list)) for v in out) else lambda v: v)
            except TypeError:
                pass
        return out


def _substitute(x, values):
    """Replace ConflictRef nodes by resolved values (MISSING deletes the slot)."""
    if isinstance(x, ConflictRef):
        return values.get(x.index, x)
    if isinstance(x, dict):
        out = {}
        for k, v in x.items():
            r = _substitute(v, values)
            if r is not M:
                out[k] = r
        return out
    if isinstance(x, list):
        out = [r for r in (_substitute(v, values) for v in x) if r is not M]
        return type(x)(out) if type(x) is not list else out
    return x


def merge(base, ours, theirs, policy: Policy = EMPTY, text_union: bool = False,
          auto_affinity: bool = False) -> Result:
    m = Merger(policy, text_union)
    merged = m.merge3((), base, ours, theirs)
    resolved = {}
    for c in m.conflicts:
        s = policy.suggest(c.path) if policy.affinity else None
        if s and c.kind in ("value", "delete-modify", "add-add"):
            c.suggestion, c.confidence = s[0], s[2]
            if auto_affinity and s[1] >= 5 and s[2] >= 0.95:
                resolved[c.index] = c.ours if s[0] == "ours" else c.theirs
                m.notes.append(("affinity", c.where()))
    if resolved:
        merged = _substitute(merged, resolved)
        m.conflicts = [c for c in m.conflicts if c.index not in resolved]
    return Result(merged, m.conflicts, m.notes)
