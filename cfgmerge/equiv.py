"""Conservative semantic equivalence of scalars. Used ONLY to avoid false conflicts when
both sides changed a value to something equivalent; never to rewrite a value."""
import re

_DUR = re.compile(r"^\s*(\d+(?:\.\d+)?)\s*(ms|s|sec|secs|seconds?|m|min|mins|minutes?|h|hr|hrs|hours?|d|days?)\s*$", re.I)
_UNIT = {"ms": 0.001, "s": 1, "sec": 1, "secs": 1, "second": 1, "seconds": 1, "m": 60, "min": 60,
         "mins": 60, "minute": 60, "minutes": 60, "h": 3600, "hr": 3600, "hrs": 3600, "hour": 3600,
         "hours": 3600, "d": 86400, "day": 86400, "days": 86400}
_QTY = re.compile(r"^\s*(\d+(?:\.\d+)?)\s*(Ki|Mi|Gi|Ti|K|M|G|T|k|m)?(B|b)?\s*$")
_QMUL = {"Ki": 1024, "Mi": 1024**2, "Gi": 1024**3, "Ti": 1024**4, "K": 1e3, "k": 1e3, "M": 1e6, "G": 1e9, "T": 1e12, "m": 1e-3}
_TRUE, _FALSE = {"true", "yes", "on", "y"}, {"false", "no", "off", "n"}


def _norm(v):
    if isinstance(v, bool):
        return ("b", v)
    if isinstance(v, (int, float)):
        return ("n", float(v))
    if isinstance(v, str):
        s = v.strip()
        low = s.lower()
        if low in _TRUE:
            return ("b", True)
        if low in _FALSE:
            return ("b", False)
        m = _DUR.match(s)
        if m:
            return ("d", float(m.group(1)) * _UNIT[m.group(2).lower()])
        m = _QTY.match(s)
        if m and (m.group(2) or m.group(3)):
            return ("q", float(m.group(1)) * _QMUL.get(m.group(2) or "", 1))
        try:
            return ("n", float(s))
        except ValueError:
            return ("s", s)
    return ("o", repr(v))


def equivalent(a, b) -> bool:
    if isinstance(a, (dict, list)) or isinstance(b, (dict, list)):
        return False
    na, nb = _norm(a), _norm(b)
    return na == nb and na[0] != "o"
