"""Merging templated YAML (Helm / Go templates, Jinja / Ansible) that is not valid YAML.

Idea: template *directive lines* (`{{- if .Values.x }}`, `{{- end }}`, `{% for ... %}`,
`{{ toYaml .Values.r | nindent 8 }}` ...) are fixed anchors. A file is split into

    yaml-segment, directive, yaml-segment, directive, ...

The segment sequence is merged with the relaxed sequence merge (so concurrent inserted blocks
union, independent edits are independent). Where *both* sides edited the same YAML segment, that
segment is merged as YAML: inline `{{ ... }}` expressions are swapped for opaque placeholders so
it parses, merged with the normal engine, and restored. Anything that cannot be proven falls
back, per segment, to a plain text merge. The result must keep template blocks balanced or the
whole file falls back to git's textual merge.
"""
import re

from .seqmerge import Chunk, merge_sequences

TAG = re.compile(r"\{\{-?.*?-?\}\}|\{%-?.*?-?%\}|\{#.*?#\}", re.S)
_MARK = ("<<<<<<<", "=======", ">>>>>>>")

_OPEN = re.compile(r"^\s*(?:if|range|with|define|block|for|macro|call|filter|autoescape|raw|trans)\b")
_CLOSE = re.compile(r"^\s*(?:end|endif|endfor|endwith|endrange|enddefine|endblock|endmacro|endcall|"
                    r"endfilter|endautoescape|endraw|endtrans)\b")


def is_templated(text: str) -> bool:
    return bool(TAG.search(text))


def _tag_body(tag: str) -> str:
    t = tag[2:-2] if tag[:2] in ("{{", "{%", "{#") else tag
    return t.strip("-").strip()


def balance(text: str):
    """Block nesting depth walked across the file; None if it ever goes negative."""
    depth = 0
    for m in TAG.finditer(text):
        tag = m.group(0)
        if tag.startswith("{#") or tag.startswith("{{/*") or tag.startswith("{{- /*"):
            continue
        body = _tag_body(tag)
        if _CLOSE.match(body):
            depth -= 1
            if depth < 0:
                return None
        elif _OPEN.match(body) and not re.match(r"^\s*else\b", body):
            # jinja one-line `{% set x %}` has no closer; only count real block openers
            depth += 1
    return depth


# ------------------------------------------------------------------ segmentation
def _directive_lines(text: str):
    """Boolean per line: the line consists only of template tags (and whitespace)."""
    lines = text.split("\n")
    starts, pos = [], 0
    for ln in lines:
        starts.append(pos)
        pos += len(ln) + 1
    only = [True] * len(lines)
    spans = [(m.start(), m.end()) for m in TAG.finditer(text)]
    has_tag = [False] * len(lines)
    # per line: non-space chars not covered by any tag?
    import bisect
    span_starts = [s for s, _ in spans]
    for i, ln in enumerate(lines):
        a, b = starts[i], starts[i] + len(ln)
        if not ln.strip():
            only[i] = False
            continue
        j = bisect.bisect_right(span_starts, b) - 1
        cov = [False] * len(ln)
        while j >= 0 and spans[j][1] > a:
            s, e = spans[j]
            for k in range(max(s, a), min(e, b)):
                cov[k - a] = True
            has_tag[i] = True
            j -= 1
        only[i] = has_tag[i] and all(cov[k] or ln[k].isspace() for k in range(len(ln)))
    return lines, only


def segment(text: str):
    """-> list of (kind, text) with kind in {"y", "d"}; joins back to `text` with "\\n"."""
    lines, only = _directive_lines(text)
    segs, cur = [], []
    for ln, is_d in zip(lines, only):
        is_d = is_d or ln.strip() == "---"
        if is_d:
            if cur:
                segs.append(("y", "\n".join(cur)))
                cur = []
            segs.append(("d", ln))
        else:
            cur.append(ln)
    if cur:
        segs.append(("y", "\n".join(cur)))
    return segs


# ------------------------------------------------------------------ fragment merge
class _Placeholders:
    def __init__(self):
        self.fwd, self.rev = {}, {}

    def hide(self, text: str) -> str:
        def sub(m):
            tag = m.group(0)
            tok = self.fwd.get(tag)
            if tok is None:
                tok = f"__CFGTPL_{len(self.fwd)}__"
                self.fwd[tag], self.rev[tok] = tok, tag
                self.fwd[tag] = tok
            return tok
        return TAG.sub(sub, text)

    def show(self, text: str) -> str:
        return re.sub(r"__CFGTPL_\d+__", lambda m: self.rev.get(m.group(0), m.group(0)), text)


def _indent_of(text: str) -> int:
    ind = None
    for ln in text.split("\n"):
        if ln.strip():
            n = len(ln) - len(ln.lstrip(" "))
            ind = n if ind is None else min(ind, n)
    return ind or 0


def _dedent(text: str, n: int) -> str:
    return "\n".join(ln[n:] if ln.strip() else ln for ln in text.split("\n"))


def _indent(text: str, n: int) -> str:
    pad = " " * n
    out = []
    for ln in text.split("\n"):
        if ln.strip() and not ln.startswith(_MARK):
            out.append(pad + ln)
        else:
            out.append(ln)
    return "\n".join(out)


def _text_merge(b: str, o: str, t: str):
    """Plain line merge of three texts -> (text, clean)."""
    from .engine import _textual
    txt, ok = _textual(b + "\n", o + "\n", t + "\n")
    if txt is None:
        return None, False
    return txt[:-1] if txt.endswith("\n") else txt, ok


def _merge_fragment(b: str, o: str, t: str, ph: _Placeholders, merge_texts):
    """Both sides edited this YAML segment: merge it as YAML when it parses, else as text."""
    if not (b.strip() and o.strip() and t.strip()):
        return _text_merge(b, o, t)
    ib, io, it = _indent_of(b), _indent_of(o), _indent_of(t)
    if not (ib == io == it):
        return _text_merge(b, o, t)
    hb, ho, ht = (ph.hide(_dedent(x, ib)) for x in (b, o, t))
    try:
        out = merge_texts(hb + "\n", ho + "\n", ht + "\n", "fragment.yaml", "yaml", _allow_template=False)
    except Exception:
        return _text_merge(b, o, t)
    if out.strategy == "textual":
        return _text_merge(b, o, t)
    text = ph.show(out.text)
    text = text[:-1] if text.endswith("\n") else text
    return _indent(text, ib), out.clean


def _line_counts(text: str):
    from collections import Counter
    return Counter(l.rstrip() for l in text.split("\n") if l.strip())


def explained_by_line_facts(base: str, ours: str, theirs: str, result: str) -> bool:
    """Post-condition for a clean template merge: the result must consist of exactly the lines
    both sides kept plus the lines either side added (as exact lines, indentation included).
    Rules out YAML re-rendering drift (quote/flow-style/indent changes) and duplicated keys."""
    b, o, t = _line_counts(base), _line_counts(ours), _line_counts(theirs)
    ref = (b & o & t) + ((o - b) | (t - b))
    return _line_counts(result) == ref


# ------------------------------------------------------------------ public
def merge_templated(base: str, ours: str, theirs: str, merge_texts):
    """-> (text, clean) or None when this strategy does not apply / cannot be trusted."""
    sb, so, st = segment(base), segment(ours), segment(theirs)
    if not any(k == "y" for k, _ in sb + so + st) or not any(k == "d" for k, _ in sb + so + st):
        return None
    bb, bo, bt = balance(base), balance(ours), balance(theirs)
    if bb is None or bo is None or bt is None:
        return None
    ids = lambda segs: [f"{k}:{t}" for k, t in segs]       # noqa: E731
    ib, io, it = ids(sb), ids(so), ids(st)
    lookup = {}
    for segs in (sb, so, st):
        for k, t in segs:
            lookup[f"{k}:{t}"] = (k, t)
    merged = merge_sequences(ib, io, it, dedupe=False, union=True)
    ph = _Placeholders()
    out, clean = [], True
    for x in merged:
        if not isinstance(x, Chunk):
            out.append(lookup[x][1])
            continue
        pair_ok = x.pairwise
        if pair_ok:
            for bi, oi, ti in zip(x.base, x.ours, x.theirs):
                kinds = {lookup[bi][0], lookup[oi][0], lookup[ti][0]}
                if kinds != {"y"}:
                    pair_ok = False
        if pair_ok:
            for bi, oi, ti in zip(x.base, x.ours, x.theirs):
                res = _merge_fragment(lookup[bi][1], lookup[oi][1], lookup[ti][1], ph, merge_texts)
                if res[0] is None:
                    return None
                out.append(res[0])
                clean = clean and res[1]
            continue
        res = _text_merge("\n".join(lookup[i][1] for i in x.base),
                          "\n".join(lookup[i][1] for i in x.ours),
                          "\n".join(lookup[i][1] for i in x.theirs))
        if res[0] is None:
            return None
        out.append(res[0])
        clean = clean and res[1]
    text = "\n".join(out)
    if clean:
        bm = balance(text)
        # the merged file must be as balanced as the inputs were
        if bm is None or not (bm == bo == bt == bb or bm == bo or bm == bt):
            return None
        if not explained_by_line_facts(base, ours, theirs, text):
            return None                            # anything invented/duplicated/re-indented: refuse
    return text, clean
