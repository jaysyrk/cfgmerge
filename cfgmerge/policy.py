"""Merge policy: optional knowledge about a file (identity keys, sortedness, atomic
subtrees). Can be hand-written or learned from history (see learn.py)."""
import fnmatch
import json
from dataclasses import dataclass, field


def norm_path(path) -> str:
    """('spec','containers',3,'name') -> 'spec.containers[].name'"""
    from .core_types import ListItem
    out = ""
    for p in path:
        if isinstance(p, (int, ListItem)):
            out += "[]"
        else:
            out += ("." if out else "") + str(p)
    return out


@dataclass
class Policy:
    identity: dict = field(default_factory=dict)       # path pattern -> ["name"] / ["metadata.name","kind"]
    sorted: set = field(default_factory=set)           # lists/maps that are kept sorted
    ordered: set = field(default_factory=set)          # lists whose order matters (no set semantics)
    atomic: set = field(default_factory=set)           # subtrees merged all-or-nothing
    affinity: dict = field(default_factory=dict)       # path -> {"ours": n, "theirs": n, "novel": n}

    def suggest(self, path, min_n=3, min_ratio=0.8):
        """-> (choice, n, ratio) from how past merges resolved a conflict at `path`, or None."""
        d = self._hit(self.affinity, path)
        if not d:
            return None
        n = sum(d.values())
        if n < min_n:
            return None
        choice, c = max(((k, v) for k, v in d.items() if k != "novel"), key=lambda kv: kv[1], default=(None, 0))
        if choice is None or c / n < min_ratio:
            return None
        return choice, n, c / n

    def _hit(self, table, path):
        n = norm_path(path)
        if n in table:
            return table[n] if isinstance(table, dict) else True
        for pat in table:
            if "*" in pat and fnmatch.fnmatchcase(n, pat):
                return table[pat] if isinstance(table, dict) else True
        return None

    def identity_for(self, path):
        v = self._hit(self.identity, path)
        if v is None:
            return None
        return tuple(tuple(f.split(".")) for f in v)

    def is_sorted(self, path):
        return bool(self._hit(self.sorted, path))

    def is_ordered(self, path):
        return bool(self._hit(self.ordered, path))

    def is_atomic(self, path):
        return bool(self._hit(self.atomic, path))

    # ---- (de)serialisation
    def to_json(self):
        return json.dumps({"identity": self.identity, "sorted": sorted(self.sorted),
                           "ordered": sorted(self.ordered), "atomic": sorted(self.atomic),
                           "affinity": self.affinity}, indent=2)

    @classmethod
    def from_json(cls, text):
        d = json.loads(text)
        return cls(identity=d.get("identity", {}), sorted=set(d.get("sorted", [])),
                   ordered=set(d.get("ordered", [])), atomic=set(d.get("atomic", [])),
                   affinity=d.get("affinity", {}))


EMPTY = Policy()
