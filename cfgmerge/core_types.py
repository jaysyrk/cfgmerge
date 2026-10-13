"""Shared sentinels and strict value helpers."""
import json


class _Missing:
    _inst = None

    def __new__(cls):
        if cls._inst is None:
            cls._inst = super().__new__(cls)
        return cls._inst

    def __repr__(self):
        return "<MISSING>"

    def __bool__(self):
        return False


MISSING = _Missing()


def same(a, b) -> bool:
    """Deep equality that keeps bool distinct from int and treats 1 == 1.0."""
    if a is MISSING or b is MISSING:
        return a is b
    if isinstance(a, bool) or isinstance(b, bool):
        return isinstance(a, bool) and isinstance(b, bool) and a == b
    if isinstance(a, dict) and isinstance(b, dict):
        return a.keys() == b.keys() and all(same(a[k], b[k]) for k in a)
    if isinstance(a, (list, tuple)) and isinstance(b, (list, tuple)):
        return len(a) == len(b) and all(same(x, y) for x, y in zip(a, b))
    if isinstance(a, (dict, list, tuple)) or isinstance(b, (dict, list, tuple)):
        return False
    try:
        return a == b and type(a) is type(b) or (
            isinstance(a, (int, float)) and isinstance(b, (int, float)) and a == b)
    except Exception:
        return False


def canon(x) -> str:
    """Stable hashable form of any plain value (order-insensitive for dicts)."""
    return json.dumps(x, sort_keys=True, default=repr, separators=(",", ":"))


class ListItem(str):
    """Path component for a list element (label is for humans; policy sees it as `[]`)."""
