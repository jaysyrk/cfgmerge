"""Format adapters: text <-> plain data, and rendering a merged tree back into the
*ours* document so comments and layout survive.

Plain data = dict / list / str / int / float / bool / None / datetime.
Multi-document YAML is a `MultiDoc` (list subclass).
`Lines` is the schema-less fallback (a list of lines).
"""
import io
import json
import os
import re
import tomllib
from collections.abc import MutableMapping, MutableSequence

class FormatError(Exception):
    pass


class MultiDoc(list):
    """Several YAML documents in one file."""


class Lines(list):
    """A text file treated as a list of lines (requirements.txt, .gitignore, unknown)."""


# ---------------------------------------------------------------- detection
_EXT = {
    ".json": "json", ".jsonc": "json", ".json5": "json", ".yaml": "yaml", ".yml": "yaml", ".toml": "toml",
    ".ini": "ini", ".cfg": "ini", ".properties": "properties", ".env": "env",
    ".xml": "xml", ".pom": "xml", ".csproj": "xml", ".plist": "xml",
}
_NAMES = {
    ".gitignore": "text", ".eslintrc": "json", ".babelrc": "json", "requirements.txt": "text", ".dockerignore": "text",
    "pipfile": "toml", "cargo.lock": "toml", ".editorconfig": "ini", ".gitconfig": "ini",
}


def detect(path: str, text: str = "") -> str:
    base = os.path.basename(path).lower()
    if base in _NAMES:
        return _NAMES[base]
    if base.startswith(".env"):
        return "env"
    if re.fullmatch(r"requirements.*\.txt", base):
        return "text"
    ext = os.path.splitext(base)[1]
    if ext in _EXT:
        return _EXT[ext]
    s = text.lstrip()
    if s[:1] in "{[" and s:
        return "json"
    if s.startswith("<?xml") or s.startswith("<"):
        return "xml"
    return "text"


# ---------------------------------------------------------------- parsing
def _yaml():
    from ruamel.yaml import YAML
    y = YAML(typ="safe")
    y.allow_duplicate_keys = False
    return y


def parse(fmt: str, text: str):
    try:
        return _PARSERS[fmt](text)
    except FormatError:
        raise
    except Exception as e:                       # any parser failure -> caller falls back
        raise FormatError(f"{fmt}: {type(e).__name__}: {str(e)[:120]}") from e


def _parse_json(text):
    try:
        return json.loads(text, object_pairs_hook=_no_dupes)
    except json.JSONDecodeError:
        from . import jsonc            # comments / trailing commas (tsconfig, eslintrc, VS Code)
        return jsonc.loads(text)


def _no_dupes(pairs):
    d = {}
    for k, v in pairs:
        if k in d:
            raise FormatError(f"duplicate key {k!r}")
        d[k] = v
    return d


def _parse_yaml(text):
    docs = list(_yaml().load_all(text))
    docs = [_plain(d) for d in docs]
    if len(docs) == 0:
        return None
    if len(docs) == 1:
        return docs[0]
    return MultiDoc(docs)


def _plain(x):
    if isinstance(x, dict):
        return {k: _plain(v) for k, v in x.items()}
    if isinstance(x, (list, tuple)):
        return [_plain(v) for v in x]
    if isinstance(x, (set, frozenset)):
        return sorted(_plain(v) for v in x)
    return x


def _parse_toml(text):
    return tomllib.loads(text)


# --- INI / properties / env share a line model
_SECTION = re.compile(r"^\s*\[([^\]]+)\]\s*(?:[;#].*)?$")
_INI_KV = re.compile(r"^(\s*)([^=:\s][^=:]*?)(\s*[=:]\s*)(.*)$")
_PROP_KV = re.compile(r"^(\s*)((?:\\.|[^=:\s\\])+)(\s*[=:]\s*|\s+)(.*)$")
_ENV_KV = re.compile(r"^(\s*)(export\s+)?([A-Za-z_][A-Za-z0-9_.\-]*)(\s*=\s*)(.*)$")


def _unquote_env(v: str) -> str:
    v = v.strip()
    if len(v) >= 2 and v[0] == v[-1] and v[0] in "\"'":
        return v[1:-1]
    m = re.match(r"^(.*?)\s+#.*$", v)
    return (m.group(1) if m else v).strip()


def _kv_lines(fmt: str, text: str):
    """-> list of entries: (kind, raw, section, key, value). kind in blank/comment/section/entry"""
    out, section = [], None
    raw_lines = text.split("\n")
    i = 0
    while i < len(raw_lines):
        raw = raw_lines[i]
        s = raw.strip()
        i += 1
        if not s:
            out.append(("blank", raw, section, None, None))
        elif s[0] in "#;" or (fmt == "properties" and s[0] == "!"):
            out.append(("comment", raw, section, None, None))
        elif fmt == "ini" and _SECTION.match(raw):
            section = _SECTION.match(raw).group(1).strip()
            out.append(("section", raw, section, None, None))
        else:
            if fmt == "env":
                m = _ENV_KV.match(raw)
                if not m:
                    raise FormatError(f"env: bad line {raw[:40]!r}")
                key, val = m.group(3), _unquote_env(m.group(5))
            else:
                m = (_INI_KV if fmt == "ini" else _PROP_KV).match(raw)
                if m:
                    key, val = m.group(2).strip(), m.group(4)
                elif fmt == "ini":                      # bare key (allow_no_value)
                    key, val = s, None
                else:
                    key, val = s, ""
                # continuation lines
                if fmt == "properties":
                    while raw.rstrip().endswith("\\") and i < len(raw_lines):
                        val = val.rstrip()[:-1] + raw_lines[i].strip()
                        raw += "\n" + raw_lines[i]
                        i += 1
                elif fmt == "ini":
                    while i < len(raw_lines) and raw_lines[i][:1] in (" ", "\t") and raw_lines[i].strip() \
                            and not _SECTION.match(raw_lines[i]):
                        val = (val or "") + "\n" + raw_lines[i].strip()
                        raw += "\n" + raw_lines[i]
                        i += 1
            out.append(("entry", raw, section, key, val))
    return out


def _parse_kv(fmt):
    def parse(text):
        data = {}
        for kind, raw, section, key, val in _kv_lines(fmt, text):
            if kind == "section":
                data.setdefault(section, {})
            elif kind == "entry":
                tgt = data if section is None else data.setdefault(section, {})
                if key in tgt:
                    raise FormatError(f"{fmt}: duplicate key {key!r}")
                tgt[key] = val
        return data
    return parse


def _parse_text(text):
    lines = text.split("\n")
    if lines and lines[-1] == "":
        lines.pop()
    return Lines(lines)


def _parse_xml(text):
    from . import xmlfmt
    return xmlfmt.parse(text)


_PARSERS = {
    "json": _parse_json, "yaml": _parse_yaml, "toml": _parse_toml,
    "ini": _parse_kv("ini"), "properties": _parse_kv("properties"), "env": _parse_kv("env"),
    "text": _parse_text, "xml": _parse_xml,
}


# ---------------------------------------------------------------- rendering helpers
def _json_style(text: str):
    indent, inline_arrays = 2, False
    for line in text.split("\n"):
        m = re.match(r"^(\t+|[ ]+)\S", line)
        if m:
            indent = "\t" if m.group(1)[0] == "\t" else len(m.group(1))
            break
    else:
        indent = None
    for line in text.split("\n"):
        if re.search(r"\[\s*[^\s\[\]{}][^\[\]{}]*\]", line):
            inline_arrays = True
            break
    ascii_only = not re.search(r"[^\x00-\x7f]", text)
    compact = bool(text) and ": " not in text and '":' in text
    return dict(indent=indent, inline_arrays=inline_arrays,
                ensure_ascii=ascii_only and "\\u" in text, trailing_newline=text.endswith("\n"),
                compact=compact)


def dump_json(data, style=None) -> str:
    style = style or dict(indent=2, inline_arrays=False, ensure_ascii=False, trailing_newline=True, compact=False)
    ind = style["indent"]
    if ind is None:                              # single-line file
        sep = (",", ":") if style["compact"] else (", ", ": ")
        s = json.dumps(data, ensure_ascii=style["ensure_ascii"], separators=sep)
        return s + ("\n" if style["trailing_newline"] else "")
    unit = "\t" if ind == "\t" else " " * ind
    ea = style["ensure_ascii"]

    def scalar(v):
        return json.dumps(v, ensure_ascii=ea)

    def enc(v, depth):
        pad, pad1 = unit * depth, unit * (depth + 1)
        if isinstance(v, dict):
            if not v:
                return "{}"
            items = [f"{pad1}{json.dumps(k, ensure_ascii=ea)}: {enc(x, depth + 1)}" for k, x in v.items()]
            return "{\n" + ",\n".join(items) + "\n" + pad + "}"
        if isinstance(v, (list, tuple)):
            if not v:
                return "[]"
            if style["inline_arrays"] and all(not isinstance(x, (dict, list)) for x in v):
                inline = "[" + ", ".join(scalar(x) for x in v) + "]"
                if len(inline) + len(pad1) <= 80:
                    return inline
            items = [f"{pad1}{enc(x, depth + 1)}" for x in v]
            return "[\n" + ",\n".join(items) + "\n" + pad + "]"
        return scalar(v)

    return enc(data, 0) + ("\n" if style["trailing_newline"] else "")


def _yaml_rt(text: str):
    from ruamel.yaml import YAML
    y = YAML(typ="rt")
    y.preserve_quotes = True
    y.width = 4096
    # sequence indent style detection
    mapping, seq, offset = 2, 2, 0
    lines = text.split("\n")
    for i in range(1, len(lines)):
        m = re.match(r"^(\s*)- ", lines[i])
        p = re.match(r"^(\s*)[^\s#-][^#]*:\s*(#.*)?$", lines[i - 1])
        if m and p:
            if len(m.group(1)) == len(p.group(1)):
                seq, offset = 2, 0
            else:
                seq, offset = 2 + (len(m.group(1)) - len(p.group(1))), len(m.group(1)) - len(p.group(1)) - 2 + 0
                seq = len(m.group(1)) - len(p.group(1)) + 2
                offset = len(m.group(1)) - len(p.group(1))
            break
    for line in lines:
        m = re.match(r"^( +)\S", line)
        if m:
            mapping = len(m.group(1)) if len(m.group(1)) in (2, 4, 6, 8) and offset == 0 else mapping
            break
    y.indent(mapping=max(mapping, 2), sequence=max(seq, 2), offset=offset)
    y.explicit_start = text.lstrip().startswith("---")
    return y


def _sync(target, merged):
    """Make `target` (a ruamel/tomlkit container from the ours document) equal `merged`,
    touching as little as possible so comments and layout stay."""
    if isinstance(merged, dict) and isinstance(target, MutableMapping):
        for k in list(target.keys()):
            if k not in merged:
                del target[k]
        for i, (k, v) in enumerate(merged.items()):
            if k in target:
                cur = target[k]
                if isinstance(v, (dict, list)) and isinstance(cur, (MutableMapping, MutableSequence)) \
                        and isinstance(v, dict) == isinstance(cur, MutableMapping):
                    _sync(cur, v)
                elif not _same(cur, v):
                    target[k] = v
            else:
                ins = getattr(target, "insert", None)
                if ins is not None and hasattr(target, "ca"):
                    ins(min(i, len(target)), k, v)
                else:
                    target[k] = v
        return
    if isinstance(merged, list) and isinstance(target, MutableSequence):
        _sync_seq(target, merged)
        return
    raise TypeError("cannot sync")


def _sync_seq(target, merged):
    """Minimal in-place edits: keep matching items (and their comments), patch
    structurally-similar replaced items, delete/insert the rest."""
    from difflib import SequenceMatcher
    from .core_types import canon
    old = list(target)
    ok = [canon(_plain(x)) for x in old]
    nk = [canon(_plain(x)) for x in merged]
    ops = SequenceMatcher(None, ok, nk, autojunk=False).get_opcodes()
    for tag, i1, i2, j1, j2 in reversed(ops):
        if tag == "equal":
            continue
        if tag == "replace" and (i2 - i1) == (j2 - j1):
            pair_ok = True
            for k in range(i2 - i1):
                o, v = old[i1 + k], merged[j1 + k]
                if isinstance(v, dict) and isinstance(o, MutableMapping) and _key_overlap(o, v) >= 0.5:
                    _sync(o, v)
                elif isinstance(v, list) and isinstance(o, MutableSequence):
                    _sync(o, v)
                else:
                    target[i1 + k] = v
            if pair_ok:
                continue
        for _ in range(i2 - i1):
            del target[i1]
        for k, v in enumerate(merged[j1:j2]):
            target.insert(i1 + k, v)


def _key_overlap(a, b):
    ka, kb = set(a.keys()), set(b.keys())
    return len(ka & kb) / max(1, len(ka | kb))


def _same(a, b):
    from .core_types import same
    return same(_plain(a), _plain(b))


def render(fmt: str, merged, ours_text: str, fresh: bool = False) -> str:
    """Merged data -> text. Preferred: patch the ours document; `fresh=True` re-emits from scratch."""
    if fmt == "json":
        style = _json_style(ours_text)
        if not fresh and ours_text.strip():
            from . import jsonc
            if not jsonc.is_strict_json(ours_text):          # keep comments / trailing commas
                try:
                    return jsonc.patch(ours_text, merged, style)
                except jsonc.JsoncError:
                    pass
        return dump_json(merged, style)
    if fmt == "yaml":
        return _render_yaml(merged, ours_text, fresh)
    if fmt == "toml":
        return _render_toml(merged, ours_text, fresh)
    if fmt in ("ini", "properties", "env"):
        return _render_kv(fmt, merged, ours_text, fresh)
    if fmt == "text":
        return "\n".join(merged) + ("\n" if ours_text.endswith("\n") or not ours_text else "")
    if fmt == "xml":
        from . import xmlfmt
        return xmlfmt.render(merged, ours_text, fresh)
    raise FormatError(f"cannot render {fmt}")


def _render_yaml(merged, ours_text, fresh):
    y = _yaml_rt(ours_text)
    buf = io.StringIO()
    if isinstance(merged, MultiDoc):
        docs_out = list(merged)
        if not fresh:
            try:
                ours_docs = list(y.load_all(ours_text))
                docs_out = _patch_docs(ours_docs, list(merged))
            except Exception:
                docs_out = list(merged)
        y.explicit_start = True
        y.dump_all(docs_out, buf)
        return buf.getvalue()
    if fresh or merged is None:
        y.dump(merged, buf)
        return buf.getvalue()
    doc = y.load(ours_text)
    if isinstance(merged, dict) and isinstance(doc, MutableMapping) or \
            isinstance(merged, list) and isinstance(doc, MutableSequence):
        _sync(doc, merged)
        y.dump(doc, buf)
    else:
        y.dump(merged, buf)
    return buf.getvalue()


def _patch_docs(ours_docs, merged_docs):
    out = []
    pool = list(ours_docs)
    for m in merged_docs:
        best = None
        for o in pool:
            if _same(o, m):
                best = o
                break
        if best is None:
            for o in pool:
                if isinstance(m, dict) and isinstance(o, MutableMapping) and \
                        (o.get("kind"), (o.get("metadata") or {}).get("name") if isinstance(o.get("metadata"), dict) else None) == \
                        (m.get("kind"), (m.get("metadata") or {}).get("name") if isinstance(m.get("metadata"), dict) else None):
                    best = o
                    break
        if best is not None:
            pool.remove(best)
            if not _same(best, m) and isinstance(m, dict) and isinstance(best, MutableMapping):
                _sync(best, m)
            out.append(best)
        else:
            out.append(m)
    return out


def _render_toml(merged, ours_text, fresh):
    import tomlkit
    if fresh:
        return tomlkit.dumps(merged)
    doc = tomlkit.parse(ours_text)
    _sync(doc, merged)
    return tomlkit.dumps(doc)


def _quote_env(val: str, orig_raw: str) -> str:
    m = _ENV_KV.match(orig_raw)
    old = m.group(5).strip() if m else ""
    if old[:1] in "\"'":
        q = old[0]
        return f"{q}{val}{q}"
    if re.search(r"\s|#|\"|'", val):
        return f'"{val}"'
    return val


def _render_kv(fmt, merged, ours_text, fresh):
    """Line-model patching: keep every comment/blank/layout line of ours."""
    entries = [] if fresh else _kv_lines(fmt, ours_text)
    sep_default = {"ini": " = ", "properties": "=", "env": "="}[fmt]

    def new_line(key, val, sep=None):
        if fmt == "env":
            return f"{key}={_quote_env(str(val), '')}"
        if fmt == "ini" and val is None:
            return key
        sval = _scalar_text(val)
        return f"{key}{sep or sep_default}{sval}"

    # group ours lines by section
    section_order = [None]
    sec_lines = {None: []}
    cur = None
    for kind, raw, section, key, val in entries:
        if kind == "section":
            cur = section
            section_order.append(cur)
            sec_lines.setdefault(cur, [])
            sec_lines[cur].append((kind, raw, key, val))
        else:
            sec_lines.setdefault(section, []).append((kind, raw, key, val))

    def flat(d):
        """merged data -> {section|None: {key: val}} + section order"""
        top = {k: v for k, v in d.items() if not isinstance(v, dict)}
        secs = {k: v for k, v in d.items() if isinstance(v, dict)}
        return top, secs

    top, secs = flat(merged) if isinstance(merged, dict) else ({}, {})
    if fmt != "ini":
        top, secs = (merged if isinstance(merged, dict) else {}), {}

    def patch_block(block, want: dict, header_raw=None):
        out, seen = [], set()
        last_key_idx = -1
        for kind, raw, key, val in block:
            if kind == "entry":
                if key not in want:
                    continue
                seen.add(key)
                if _scalar_text(want[key]) != _scalar_text(val) and not (want[key] is None and val is None):
                    m = (_ENV_KV if fmt == "env" else _INI_KV if fmt == "ini" else _PROP_KV).match(raw.split("\n")[0])
                    if fmt == "env" and m:
                        raw = f"{m.group(1)}{m.group(2) or ''}{m.group(3)}{m.group(4)}{_quote_env(str(want[key]), raw)}"
                    elif m:
                        sep = m.group(3)
                        raw = f"{m.group(1)}{m.group(2) if fmt != 'ini' else m.group(2)}{sep}{_scalar_text(want[key])}"
                    else:
                        raw = new_line(key, want[key])
                out.append(raw)
                last_key_idx = len(out) - 1
            else:
                out.append(raw)
        pending = [(k, v) for k, v in want.items() if k not in seen]
        if pending:
            idx = last_key_idx + 1 if last_key_idx >= 0 else len(out)
            # keep trailing blank lines after the last entry
            if last_key_idx < 0:
                while idx > 0 and out[idx - 1].strip() == "":
                    idx -= 1
            add = [new_line(k, v) for k, v in pending]
            out[idx:idx] = add
        return out

    result = []
    top_block = sec_lines.get(None, [])
    result.extend(patch_block(top_block, top))
    done = set()
    for s in section_order[1:]:
        if s in done:
            continue
        done.add(s)
        block = sec_lines[s]
        if s not in secs:
            continue                              # section deleted
        header = block[0][1]
        body = patch_block(block[1:], secs[s])
        result.append(header)
        result.extend(body)
    for s, want in secs.items():
        if s not in done:
            if result and result[-1].strip() != "":
                result.append("")
            result.append(f"[{s}]")
            result.extend(new_line(k, v) for k, v in want.items())
    text = "\n".join(result)
    if not text.endswith("\n") and (ours_text.endswith("\n") or not ours_text):
        text += "\n"
    return text


def _scalar_text(v) -> str:
    if v is None:
        return ""
    if isinstance(v, bool):
        return "true" if v else "false"
    return str(v)
