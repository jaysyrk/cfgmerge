"""Semantic diff: what changed in meaning, ignoring formatting and ordering noise."""
from dataclasses import dataclass
from difflib import SequenceMatcher

from .core_types import MISSING, canon, same
from .identity import ident, infer_key


@dataclass
class Change:
    kind: str          # add | remove | change
    path: tuple
    old: object = MISSING
    new: object = MISSING

    def render(self) -> str:
        p = ".".join(str(x) for x in self.path) or "<root>"
        short = lambda v: (canon(v) if isinstance(v, (dict, list)) else repr(v))[:70]
        if self.kind == "add":
            return f"+ {p}: {short(self.new)}"
        if self.kind == "remove":
            return f"- {p}: {short(self.old)}"
        return f"~ {p}: {short(self.old)} -> {short(self.new)}"


def diff(a, b, path=()):
    out = []
    if same(a, b):
        return out
    if isinstance(a, dict) and isinstance(b, dict):
        for k in a:
            if k not in b:
                out.append(Change("remove", path + (k,), old=a[k]))
        for k in b:
            if k not in a:
                out.append(Change("add", path + (k,), new=b[k]))
            elif not same(a[k], b[k]):
                out.extend(diff(a[k], b[k], path + (k,)))
        return out
    if isinstance(a, list) and isinstance(b, list):
        key = infer_key(a, a, b) if a else infer_key([], b, b)
        if key:
            try:
                am = {ident(i, key): i for i in a}
                bm = {ident(i, key): i for i in b}
                if len(am) == len(a) and len(bm) == len(b):
                    for k in am:
                        label = "[" + ",".join(str(x).strip('"') for x in k) + "]"
                        if k not in bm:
                            out.append(Change("remove", path + (label,), old=am[k]))
                        elif not same(am[k], bm[k]):
                            out.extend(diff(am[k], bm[k], path + (label,)))
                    for k in bm:
                        if k not in am:
                            label = "[" + ",".join(str(x).strip('"') for x in k) + "]"
                            out.append(Change("add", path + (label,), new=bm[k]))
                    return out
            except Exception:
                pass
        ca, cb = [canon(x) for x in a], [canon(x) for x in b]
        for tag, i1, i2, j1, j2 in SequenceMatcher(None, ca, cb, autojunk=False).get_opcodes():
            if tag == "equal":
                continue
            for x in a[i1:i2]:
                out.append(Change("remove", path + ("[]",), old=x))
            for x in b[j1:j2]:
                out.append(Change("add", path + ("[]",), new=x))
        return out
    out.append(Change("change", path, old=a, new=b))
    return out
