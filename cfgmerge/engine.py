"""File-level API: text in -> merged text out, with a safety net.

Pipeline: detect format -> textual fast paths -> parse -> semantic merge ->
render into the `ours` document -> re-parse and verify -> fallbacks -> markers.
"""
import json
import os
import re
import subprocess
import tempfile
from dataclasses import dataclass, field

from . import formats as F
from . import template as T
from .core_types import MISSING, same
from .merge import ConflictRef, merge
from .policy import EMPTY, Policy

REWRITE_MIN_CHANGES = 15       # leaf facts changed on each side
REWRITE_FRACTION = 0.5         # ... and at least this share of the base
REWRITE_OVERLAP = 0.5          # ... of which this share is the same facts touched by both

PH = "<<<CFGMERGE:{}>>>"
_PH_RE = re.compile(r"<<<CFGMERGE:(\d+)>>>")


@dataclass
class Output:
    text: str
    clean: bool
    fmt: str
    strategy: str                                  # fast | structured | fresh | textual
    conflicts: list = field(default_factory=list)
    notes: list = field(default_factory=list)
    data: object = None                            # merged data (None for textual)


def _textual(base, ours, theirs):
    """Plain diff3 via `git merge-file`; internal line merge if git is unavailable."""
    try:
        with tempfile.TemporaryDirectory() as d:
            paths = []
            for name, txt in (("ours", ours), ("base", base), ("theirs", theirs)):
                p = os.path.join(d, name)
                with open(p, "w") as f:
                    f.write(txt)
                paths.append(p)
            r = subprocess.run(["git", "merge-file", "-p", *paths], capture_output=True, text=True)
            if r.returncode >= 0 and r.returncode < 127:
                return r.stdout, r.returncode == 0
    except Exception:
        pass
    from .merge import merge as m
    res = m(F.parse("text", base), F.parse("text", ours), F.parse("text", theirs))
    return None, not res.conflicts


def _looks_list_like(lines):
    body = [l for l in lines if l.strip()]
    if not body:
        return True
    simple = sum(1 for l in body if l.lstrip().startswith("#") or len(l.split()) <= 2)
    return simple / len(body) >= 0.8


def _facts(x, path=()):
    if isinstance(x, dict):
        for k, v in x.items():
            yield from _facts(v, path + (str(k),))
    elif isinstance(x, list):
        if not x:
            yield (path + ("[]",), "[]")
        for v in x:
            yield from _facts(v, path + ("[]",))
    else:
        yield (path, repr(x))


def is_big_rewrite(base, ours, theirs) -> bool:
    """Both sides rewrote most of the file, largely the same parts of it. A tree merge of two
    independent rewrites would stitch them together; that is not trustworthy, defer to text."""
    if base is MISSING or base is None:
        return False
    fb, fo, ft = set(_facts(base)), set(_facts(ours)), set(_facts(theirs))
    if not fb:
        return False
    co, ct = fo ^ fb, ft ^ fb
    if min(len(co), len(ct)) < REWRITE_MIN_CHANGES:
        return False
    if min(len(co), len(ct)) / len(fb) < REWRITE_FRACTION:
        return False
    return len(co & ct) / min(len(co), len(ct)) >= REWRITE_OVERLAP


def _materialize(x):
    """Replace ConflictRef objects by placeholder strings (so any renderer can emit them)."""
    if isinstance(x, ConflictRef):
        return PH.format(x.index)
    if isinstance(x, dict):
        return {k: _materialize(v) for k, v in x.items()}
    if isinstance(x, F.MultiDoc):
        return F.MultiDoc(_materialize(v) for v in x)
    if isinstance(x, F.Lines):
        return F.Lines(_materialize(v) for v in x)
    if isinstance(x, list):
        return [_materialize(v) for v in x]
    return x


def _side_text(fmt, value, line, indent):
    """Text of one side of a conflict at the placeholder's line."""
    if value is MISSING:
        return []
    m = _PH_RE.search(line)
    pre, post = line[:m.start()], line[m.end():]
    # strip quotes the renderer put around the placeholder
    q = pre[-1:] if pre[-1:] in "\"'" and post[:1] == pre[-1:] else ""
    if q:
        pre, post = pre[:-1], post[1:]
    if not isinstance(value, (dict, list)):
        if fmt == "json":
            s = json.dumps(value)
        elif isinstance(value, bool):
            s = "true" if value else "false"
        elif value is None:
            s = "null" if fmt in ("yaml", "json") else ""
        else:
            s = str(value)
            if q and fmt == "yaml" and re.search(r"[:#]|^\s|\s$", s):
                s = json.dumps(s)
            elif q and fmt in ("toml",):
                s = json.dumps(s)
        return [pre + s + post]
    if fmt == "json":
        return [pre + json.dumps(value) + post]
    frag = F.render(fmt if fmt in ("yaml",) else "yaml", value, "", fresh=True).rstrip("\n").split("\n")
    pad = " " * (len(pre) - len(pre.lstrip()))
    head = pre.rstrip()
    return [head] + [pad + "  " + l for l in frag]


def _apply_markers(fmt, text, conflicts):
    out = []
    for line in text.split("\n"):
        m = _PH_RE.search(line)
        if not m:
            out.append(line)
            continue
        c = conflicts[int(m.group(1))]
        ind = line[:len(line) - len(line.lstrip())]
        out.append("<<<<<<< ours")
        out.extend(_side_text(fmt, c.ours, line, ind))
        out.append("=======")
        out.extend(_side_text(fmt, c.theirs, line, ind))
        out.append(">>>>>>> theirs")
    return "\n".join(out)


def merge_texts(base: str, ours: str, theirs: str, path: str = "", fmt: str = None,
                policy: Policy = EMPTY, base_missing: bool = False, auto_affinity: bool = False,
                _allow_template: bool = True) -> Output:
    fmt = fmt or F.detect(path, ours or theirs or base)
    # ---- textual fast paths: never re-render what nobody changed
    if ours == theirs:
        return Output(ours, True, fmt, "fast")
    if ours == base and not base_missing:
        return Output(theirs, True, fmt, "fast")
    if theirs == base and not base_missing:
        return Output(ours, True, fmt, "fast")
    try:
        pb = MISSING if base_missing else F.parse(fmt, base)
        po, pt = F.parse(fmt, ours), F.parse(fmt, theirs)
    except F.FormatError:
        txt, ok = _textual(base, ours, theirs)
        if _allow_template and fmt == "yaml" and not base_missing and T.is_templated(base + ours + theirs) \
                and not (ok and txt is not None and T.balance(txt) is not None):
            # Helm / Go-template / Jinja YAML. git's line merge is already right most of the time
            # here, so it stays primary; the structural merge only gets a say where git conflicts,
            # and only if its result is exactly explained by the line facts (see template.py).
            res = T.merge_templated(base, ours, theirs, merge_texts)
            if res is not None and res[1]:
                return Output(res[0], True, fmt, "template")
        return Output(txt if txt is not None else ours, ok, fmt, "textual")
    if same(po, pt):                             # formatting-only difference on one or both sides
        return Output(ours, True, fmt, "fast")
    if pb is not MISSING and same(po, pb):       # ours only reformatted
        return Output(theirs, True, fmt, "fast")
    if pb is not MISSING and same(pt, pb):
        return Output(ours, True, fmt, "fast")
    if pb is not MISSING and is_big_rewrite(pb, po, pt):
        txt, ok = _textual(base, ours, theirs)
        if txt is not None:
            return Output(txt, ok, fmt, "textual")
    text_union = fmt == "text" and _looks_list_like(list(po) + list(pt))
    res = merge(pb, po, pt, policy, text_union=text_union, auto_affinity=auto_affinity)
    data = _materialize(res.merged)
    ph_data = data
    strategy = "structured"
    text = None
    for fresh in (False, True):
        try:
            cand = F.render(fmt, ph_data, ours, fresh=fresh, donor_text=theirs)
            back = F.parse(fmt, cand)
        except Exception:
            continue
        if same(back, ph_data) or (fmt == "text" and list(back) == list(ph_data)):
            text, strategy = cand, ("structured" if not fresh else "fresh")
            break
    if text is None:                             # cannot prove the render: textual fallback
        txt, ok = _textual(base if not base_missing else "", ours, theirs)
        return Output(txt if txt is not None else ours, ok, fmt, "textual")
    if res.conflicts:
        text = _apply_markers(fmt, text, res.conflicts)
    if "\r\n" in ours and "\r" not in text:           # keep the file's line endings
        text = text.replace("\n", "\r\n")
    return Output(text, not res.conflicts, fmt, strategy, res.conflicts, res.notes,
                  None if res.conflicts else res.merged)
