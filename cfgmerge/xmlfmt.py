"""XML adapter.

Element -> data:
    leaf (no attrs, no children)  -> str (stripped text)
    otherwise                     -> {"@a": {attr: v}, "#text": str, "<child-tag>": [child, ...], ...}
Children are *always* lists per tag so a tag never flips between scalar and list when
one side adds a sibling. Comments / processing instructions are not part of the data;
rendering patches the `ours` lxml tree so they (and layout) survive.
"""
import re

from .core_types import canon

try:
    from lxml import etree
except ImportError:                                   # pragma: no cover
    etree = None


def _parser():
    return etree.XMLParser(remove_blank_text=False, resolve_entities=False, load_dtd=False,
                           no_network=True, huge_tree=False)


def _is_el(n):
    return isinstance(n.tag, str)


def to_data(el):
    kids = [c for c in el if _is_el(c)]
    text = (el.text or "").strip()
    attrs = dict(el.attrib)
    if not kids and not attrs:
        return text
    d = {}
    if attrs:
        d["@a"] = attrs
    if text:
        d["#text"] = text
    for c in kids:
        d.setdefault(c.tag, []).append(to_data(c))
    return d


def parse(text: str):
    if etree is None:
        raise RuntimeError("lxml not installed")
    root = etree.fromstring(text.encode("utf-8"), _parser())
    return {root.tag: to_data(root)}


# ------------------------------------------------------------------ rendering
def _indent_unit(root):
    for el in root.iter():
        if el.text and el.text.startswith("\n") and el.text.strip() == "" and len(el):
            return el.text[1:] or "  "
    return "  "


def _build(parent, tag, data, unit, level):
    el = etree.SubElement(parent, tag) if parent is not None else etree.Element(tag)
    _fill(el, data, unit, level)
    return el


def _fill(el, data, unit, level):
    if isinstance(data, str):
        el.text = data or None
        return
    for k, v in (data.get("@a") or {}).items():
        el.set(k, str(v))
    kids = [(k, v) for k, v in data.items() if not k.startswith("@") and k != "#text"]
    nchild = sum(len(v) for _, v in kids)
    if "#text" in data:
        el.text = data["#text"]
    pad = "\n" + unit * (level + 1)
    for k, vs in kids:
        for v in vs:
            _build(el, k, v, unit, level + 1)
    if nchild and "#text" not in data:
        el.text = pad
        for c in el:
            c.tail = pad
        el[-1].tail = "\n" + unit * level


def _sync(el, data, unit, level):
    if isinstance(data, str):
        for c in [c for c in el if _is_el(c)]:
            el.remove(c)
        el.text = data or None
        return
    want_attrs = {k: str(v) for k, v in (data.get("@a") or {}).items()}
    for k in list(el.attrib):
        if k not in want_attrs:
            del el.attrib[k]
    for k, v in want_attrs.items():
        if el.get(k) != v:
            el.set(k, v)
    if "#text" in data:
        if (el.text or "").strip() != data["#text"]:
            el.text = data["#text"]
    elif not [c for c in el if _is_el(c)] and (el.text or "").strip():
        el.text = None
    # children, tag by tag
    cur_by_tag = {}
    for c in el:
        if _is_el(c):
            cur_by_tag.setdefault(c.tag, []).append(c)
    want = {k: v for k, v in data.items() if not k.startswith("@") and k != "#text"}
    for tag in list(cur_by_tag):
        if tag not in want:
            for c in cur_by_tag[tag]:
                _remove(el, c)
    for tag, vs in want.items():
        existing = cur_by_tag.get(tag, [])
        _sync_children(el, tag, existing, vs, unit, level)


def _remove(parent, child):
    prev = child.getprevious()
    if child.tail and prev is not None and not (prev.tail or "").strip():
        pass
    nxt_tail = child.tail
    if prev is not None:
        prev.tail = nxt_tail if prev.tail is None or not prev.tail.strip() else prev.tail
    elif parent.text is not None and not parent.text.strip():
        parent.text = nxt_tail
    parent.remove(child)


def _sync_children(parent, tag, existing, wanted, unit, level):
    from difflib import SequenceMatcher
    ck_old = [canon(to_data(c)) for c in existing]
    ck_new = [canon(w) for w in wanted]
    ops = SequenceMatcher(None, ck_old, ck_new, autojunk=False).get_opcodes()
    for t, i1, i2, j1, j2 in reversed(ops):
        if t == "equal":
            continue
        if t == "replace" and (i2 - i1) == (j2 - j1):
            for k in range(i2 - i1):
                _sync(existing[i1 + k], wanted[j1 + k], unit, level + 1)
            continue
        anchor = existing[i1 - 1] if i1 > 0 else None
        for c in existing[i1:i2]:
            _remove(parent, c)
        for w in reversed(wanted[j1:j2]):
            new = etree.Element(tag)
            _fill(new, w, unit, level + 1)
            _insert_after(parent, anchor, new, unit, level)


def _insert_after(parent, anchor, new, unit, level):
    pad = "\n" + unit * (level + 1)
    if anchor is not None:
        old = anchor.tail
        anchor.addnext(new)
        new.tail = old                      # whatever followed the anchor now follows `new`
        anchor.tail = pad                   # indentation in front of `new`
        return
    kids = [c for c in parent if _is_el(c)]
    if kids:                                          # before the first element of this tag-run
        first = kids[0]
        new.tail = pad if not (first.getprevious() is None and (parent.text or "").strip() == "") else pad
        first.addprevious(new)
        if parent.text is None or parent.text.strip() == "":
            parent.text = parent.text or pad
        return
    # parent had no element children
    parent.text = pad
    new.tail = "\n" + unit * level
    parent.append(new)


def render(merged, ours_text: str, fresh: bool) -> str:
    (tag, data), = merged.items()
    decl = ""
    m = re.match(r"^\s*(<\?xml[^>]*\?>)\s*", ours_text)
    if m:
        decl = m.group(1) + "\n"
    if fresh or not ours_text.strip():
        root = etree.Element(tag)
        _fill(root, data, "  ", 0)
        return decl + etree.tostring(root, encoding="unicode") + "\n"
    root = etree.fromstring(ours_text.encode("utf-8"), _parser())
    unit = _indent_unit(root)
    if root.tag != tag:
        raise ValueError("root changed")
    _sync(root, data, unit, 0)
    # keep the prolog (declaration / comments / doctype) exactly as in ours
    start = re.search(r"<" + re.escape(re.sub(r"^\{.*\}", "", root.tag)) + r"[\s>/]", ours_text)
    prolog = ours_text[:start.start()] if start else decl
    body = etree.tostring(root, encoding="unicode")
    return prolog + body + ("\n" if ours_text.endswith("\n") else "")
