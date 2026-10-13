"""JSON with comments and trailing commas (tsconfig.json, .eslintrc, VS Code settings...).

`loads` gives plain data. `patch` rewrites the *ours* text so that it equals a merged tree while
every untouched byte (comments, blank lines, trailing commas, quoting) stays exactly as written:
the text is parsed into spans, then objects/arrays are rebuilt from their own original gaps.
"""
import json
from difflib import SequenceMatcher

from .core_types import canon


class JsoncError(ValueError):
    pass


class _Node:
    __slots__ = ("kind", "start", "end", "members", "items", "value")

    def __init__(self, kind, start):
        self.kind, self.start, self.end = kind, start, start
        self.members, self.items, self.value = [], [], None


class _Member:
    __slots__ = ("key", "start", "end", "node")


class _Parser:
    def __init__(self, text):
        self.t, self.i, self.n = text, 0, len(text)

    def ws(self):
        t = self.t
        while self.i < self.n:
            c = t[self.i]
            if c in " \t\r\n﻿":
                self.i += 1
            elif t.startswith("//", self.i):
                j = t.find("\n", self.i)
                self.i = self.n if j < 0 else j
            elif t.startswith("/*", self.i):
                j = t.find("*/", self.i + 2)
                if j < 0:
                    raise JsoncError("unterminated comment")
                self.i = j + 2
            else:
                break

    def string(self):
        s = self.i
        self.i += 1
        while self.i < self.n:
            c = self.t[self.i]
            if c == "\\":
                self.i += 2
                continue
            if c == '"':
                self.i += 1
                return s, self.i
            self.i += 1
        raise JsoncError("unterminated string")

    def value(self):
        self.ws()
        if self.i >= self.n:
            raise JsoncError("unexpected end")
        c = self.t[self.i]
        if c == "{":
            return self.obj()
        if c == "[":
            return self.arr()
        node = _Node("scalar", self.i)
        if c == '"':
            s, e = self.string()
        else:
            s = self.i
            while self.i < self.n and self.t[self.i] not in ",]} \t\r\n" and not self.t.startswith(("//", "/*"), self.i):
                self.i += 1
            e = self.i
        node.start, node.end = s, e
        try:
            node.value = json.loads(self.t[s:e])
        except ValueError as ex:
            raise JsoncError(str(ex))
        return node

    def obj(self):
        node = _Node("obj", self.i)
        self.i += 1
        while True:
            self.ws()
            if self.i >= self.n:
                raise JsoncError("unterminated object")
            if self.t[self.i] == "}":
                self.i += 1
                break
            if self.t[self.i] != '"':
                raise JsoncError(f"expected key at {self.i}")
            m = _Member()
            ks, ke = self.string()
            m.key, m.start = json.loads(self.t[ks:ke]), ks
            self.ws()
            if self.t[self.i:self.i + 1] != ":":
                raise JsoncError("expected ':'")
            self.i += 1
            m.node = self.value()
            m.end = m.node.end
            node.members.append(m)
            self.ws()
            if self.t[self.i:self.i + 1] == ",":
                self.i += 1
            elif self.t[self.i:self.i + 1] != "}":
                raise JsoncError("expected ',' or '}'")
        node.end = self.i
        return node

    def arr(self):
        node = _Node("arr", self.i)
        self.i += 1
        while True:
            self.ws()
            if self.i >= self.n:
                raise JsoncError("unterminated array")
            if self.t[self.i] == "]":
                self.i += 1
                break
            node.items.append(self.value())
            self.ws()
            if self.t[self.i:self.i + 1] == ",":
                self.i += 1
            elif self.t[self.i:self.i + 1] != "]":
                raise JsoncError("expected ',' or ']'")
        node.end = self.i
        return node


def _spans(text):
    p = _Parser(text)
    node = p.value()
    p.ws()
    if p.i != p.n:
        raise JsoncError("trailing content")
    return node


def _plain(node):
    if node.kind == "scalar":
        return node.value
    if node.kind == "arr":
        return [_plain(x) for x in node.items]
    out = {}
    for m in node.members:
        if m.key in out:
            raise JsoncError(f"duplicate key {m.key!r}")
        out[m.key] = _plain(m.node)
    return out


def loads(text):
    return _plain(_spans(text))


def is_strict_json(text) -> bool:
    try:
        json.loads(text)
        return True
    except ValueError:
        return False


# ------------------------------------------------------------------ patching
def _dump(value, style, depth):
    from .formats import dump_json
    unit = "\t" if style["indent"] == "\t" else " " * (style["indent"] or 2)
    s = dump_json(value, {**style, "indent": style["indent"] or 2, "trailing_newline": False})
    if depth:                                   # re-indent continuation lines to the target depth
        pad = unit * depth
        s = ("\n" + pad).join(s.split("\n"))
    return s


def _indent_at(text, pos):
    ls = text.rfind("\n", 0, pos) + 1
    j = ls
    while j < pos and text[j] in " \t":
        j += 1
    return text[ls:j]


def _render(text, node, new, style):
    """Text for `node` after it has been made equal to `new`."""
    old_text = text[node.start:node.end]
    if node.kind == "scalar":
        return old_text if _same_scalar(node.value, new) else _dump(new, style, _depth(text, node.start, style))
    if node.kind == "obj" and isinstance(new, dict):
        return _render_obj(text, node, new, style)
    if node.kind == "arr" and isinstance(new, list):
        return _render_arr(text, node, new, style)
    return _dump(new, style, _depth(text, node.start, style))


def _same_scalar(a, b):
    return not isinstance(b, (dict, list)) and type(a) is type(b) and a == b or \
        (isinstance(a, (int, float)) and isinstance(b, (int, float)) and not isinstance(a, bool)
         and not isinstance(b, bool) and a == b)


def _depth(text, pos, style):
    ind = _indent_at(text, pos)
    unit = "\t" if style["indent"] == "\t" else " " * (style["indent"] or 2)
    return len(ind) // max(1, len(unit)) if unit else 0


def _rebuild(text, node, parts, kept_gap, default_gap):
    """parts: [(orig_index or None, rendered_text)] in output order. Elements keep their original
    gap (comma + whitespace + comments) in front of them; new ones get the default gap."""
    elems = node.members if node.kind == "obj" else node.items
    base = _indent_at(text, node.start)
    if not elems:
        if not parts:
            return text[node.start:node.end]
        return (text[node.start] + default_gap[1:] + default_gap.join(p for _, p in parts)
                + "\n" + base + text[node.end - 1])
    if not parts:
        return text[node.start] + "\n" + base + text[node.end - 1]
    out = [text[node.start:elems[0].start]]
    for n, (idx, rendered) in enumerate(parts):
        if n > 0:
            out.append(kept_gap.get(idx, default_gap) if idx is not None else default_gap)
        out.append(rendered)
    out.append(text[elems[-1].end:node.end])
    return "".join(out)


def _gaps(text, spans):
    """Original gap in front of each element (comma + whitespace + comments)."""
    g = {}
    for i in range(1, len(spans)):
        g[i] = text[spans[i - 1][1]:spans[i][0]]
    return g


def _default_gap(text, node, style):
    ind = _indent_at(text, node.members[0].start if node.kind == "obj" and node.members
                     else node.items[0].start if node.items else node.start)
    inline = "\n" not in text[node.start:node.end]
    if inline:
        return ", "
    child_ind = ind if (node.members or node.items) else _indent_at(text, node.start) + (
        "\t" if style["indent"] == "\t" else " " * (style["indent"] or 2))
    return ",\n" + child_ind


def _render_obj(text, node, new, style):
    by_key = {m.key: m for m in node.members}
    order = {m.key: i for i, m in enumerate(node.members)}
    spans = [(m.start, m.end) for m in node.members]
    kept_gap = _gaps(text, spans)
    default = _default_gap(text, node, style)
    parts = []
    depth_child = _depth(text, node.members[0].start, style) if node.members else _depth(text, node.start, style) + 1
    for k, v in new.items():
        if k in by_key:
            m = by_key[k]
            val = _render(text, m.node, v, style)
            parts.append((order[k], text[m.start:m.node.start] + val))
        else:
            parts.append((None, f"{json.dumps(k, ensure_ascii=False)}: {_dump(v, style, depth_child)}"))
    return _rebuild(text, node, parts, kept_gap, default)


def _render_arr(text, node, new, style):
    old = [_plain(x) for x in node.items]
    ok = [canon(x) for x in old]
    nk = [canon(x) for x in new]
    kept_gap = _gaps(text, [(x.start, x.end) for x in node.items])
    default = _default_gap(text, node, style)
    depth_child = _depth(text, node.items[0].start, style) if node.items else _depth(text, node.start, style) + 1
    out = []                                    # (orig idx or None, text)
    for tag, i1, i2, j1, j2 in SequenceMatcher(None, ok, nk, autojunk=False).get_opcodes():
        if tag == "equal":
            for a in range(i1, i2):
                out.append((a, text[node.items[a].start:node.items[a].end]))
        elif tag == "replace" and (i2 - i1) == (j2 - j1):
            for k in range(i2 - i1):
                it = node.items[i1 + k]
                out.append((i1 + k, _render(text, it, new[j1 + k], style)))
        else:
            for b in range(j1, j2):
                out.append((None, _dump(new[b], style, depth_child)))
    return _rebuild(text, node, out, kept_gap, default)


def patch(ours_text: str, merged, style) -> str:
    root = _spans(ours_text)
    lead = ours_text[:root.start]
    tail = ours_text[root.end:]
    return lead + _render(ours_text, root, merged, style) + tail
