"""Validation helpers behind the pre-commit hooks and the GitHub Action.

check   a config file parses and carries no leftover conflict markers
audit   a *merge result* did not silently lose, or break, config content that both histories
        agree on (the exact failure mode of a textual three-way merge of structured files)
summary a markdown semantic diff of the config files a change touches
"""
import fnmatch
import os
import re
import subprocess
from collections import Counter
from dataclasses import dataclass, field

from . import formats as F
from . import template as T
from .diff import diff

STRUCTURED = {"json", "yaml", "toml", "ini", "properties", "env", "xml"}
_MARK_OPEN = re.compile(r"^<<<<<<<( .*)?$")
_MARK_MID = re.compile(r"^=======$")
_MARK_CLOSE = re.compile(r"^>>>>>>>( .*)?$")


@dataclass
class Finding:
    severity: str            # error | warning
    kind: str                # parse-error | conflict-marker | invalid-merge | lost-content
    path: str
    message: str
    line: int = 0
    details: list = field(default_factory=list)


def _git(repo, *args, check=False):
    return subprocess.run(["git", "-C", repo, *args], capture_output=True, text=True, check=check)


def _show(repo, spec):
    r = subprocess.run(["git", "-C", repo, "show", spec], capture_output=True)
    return r.stdout.decode("utf-8", "replace") if r.returncode == 0 else None


def is_config_path(path: str) -> bool:
    return F.detect(path, "") in STRUCTURED


def matches(path: str, globs) -> bool:
    return not globs or any(fnmatch.fnmatch(path, g) or fnmatch.fnmatch(os.path.basename(path), g) for g in globs)


# ----------------------------------------------------------------- check
def find_markers(text: str):
    """Line numbers of a conflict block (needs open AND close marker, to avoid false hits)."""
    lines = text.split("\n")
    opens = [i for i, l in enumerate(lines) if _MARK_OPEN.match(l)]
    closes = [i for i, l in enumerate(lines) if _MARK_CLOSE.match(l)]
    mids = [i for i, l in enumerate(lines) if _MARK_MID.match(l)]
    if opens and closes and mids:
        return [i + 1 for i in opens]
    return []


def check_text(path: str, text: str):
    out = []
    for ln in find_markers(text):
        out.append(Finding("error", "conflict-marker", path, "unresolved merge conflict marker", ln))
    fmt = F.detect(path, text)
    if fmt in STRUCTURED:
        try:
            F.parse(fmt, text)
        except F.FormatError as e:
            if fmt == "yaml" and T.is_templated(text):
                return out                         # Helm/Jinja: not YAML on its own, by design
            if not out:                            # markers already explain a parse failure
                m = re.search(r"line (\d+)", str(e))
                out.append(Finding("error", "parse-error", path, str(e), int(m.group(1)) if m else 0))
    return out


def check_files(paths, root="."):
    out = []
    for p in paths:
        full = os.path.join(root, p)
        if not os.path.isfile(full):
            continue
        try:
            text = open(full, encoding="utf-8").read()
        except (UnicodeDecodeError, OSError):
            continue
        out.extend(check_text(p, text))
    return out


# ----------------------------------------------------------------- audit
def _leaves(x, path=()):
    from .core_types import canon
    if isinstance(x, dict):
        for k, v in x.items():
            yield from _leaves(v, path + (str(k),))
    elif isinstance(x, list):
        if not x:
            yield (path + ("[]",), "[]")
        for v in x:
            yield from _leaves(v, path + ("[]",))
    else:
        yield (path, canon(x))


def audit_texts(path, base, ours, theirs, result):
    """Findings for one file of one merge. `result` is the merged text under audit."""
    fmt = F.detect(path, ours or theirs)
    out = []
    structured = fmt in STRUCTURED
    try:
        if not structured:
            raise F.FormatError("not structured")
        pb, po, pt = (F.parse(fmt, x) for x in (base, ours, theirs))
        facts = lambda x: set(_leaves(F.parse(fmt, x)))                 # noqa: E731
        fb, fo, ft = set(_leaves(pb)), set(_leaves(po)), set(_leaves(pt))
        try:
            fr = facts(result)
        except F.FormatError as e:
            return [Finding("error", "invalid-merge", path,
                            f"merge result is not valid {fmt} although both inputs were: {e}")]
        ref = (fb & fo & ft) | (fo - fb) | (ft - fb)
        values = Counter(p for p, _ in ref if "[]" not in p)
        lost = [f for f in ref - fr if values[f[0]] <= 1 or "[]" in f[0]]
        # a path with two different values on the two sides is a real conflict a human decided
        if lost:
            out.append(Finding("error", "lost-content", path,
                               f"{len(lost)} value(s) both histories agree on are missing from the merge",
                               details=[f"{'.'.join(p)} = {v[:60]}" for p, v in sorted(lost)[:6]]))
        return out
    except F.FormatError:
        pass
    if fmt == "yaml" and T.is_templated(base + ours + theirs + result):
        cnt = lambda s: Counter(l.rstrip() for l in s.split("\n") if l.strip())   # noqa: E731
        b, o, t, r = cnt(base), cnt(ours), cnt(theirs), cnt(result)
        ref = (b & o & t) + ((o - b) | (t - b))
        lost = ref - r
        bal = T.balance(result)
        if bal is None or (T.balance(ours) == 0 and bal != 0):
            out.append(Finding("error", "invalid-merge", path, "template blocks (if/end) are unbalanced in the merge"))
        if lost:
            out.append(Finding("error", "lost-content", path,
                               f"{sum(lost.values())} line(s) both histories agree on are missing",
                               details=[l.strip()[:70] for l in list(lost)[:6]]))
    return out


def audit_merge_commit(repo=".", rev="HEAD", globs=None):
    parents = _git(repo, "rev-list", "--parents", "-n", "1", rev).stdout.split()[1:]
    if len(parents) != 2:
        return None
    p1, p2 = parents
    mb = _git(repo, "merge-base", p1, p2).stdout.split()
    if len(mb) != 1:
        return []
    names = set(_git(repo, "diff", "--name-only", mb[0], p1).stdout.split("\n")) & \
        set(_git(repo, "diff", "--name-only", mb[0], p2).stdout.split("\n"))
    out = []
    for name in sorted(n for n in names if n and (is_config_path(n) or T.is_templated(n))):
        if not matches(name, globs):
            continue
        texts = [_show(repo, f"{r}:{name}") for r in (mb[0], p1, p2, rev)]
        if any(t is None for t in texts):
            continue
        if texts[1] == texts[2]:
            continue
        out.extend(audit_texts(name, *texts))
    return out


def audit_index(repo="."):
    """Audit the staged result of an in-progress merge (used by the pre-merge-commit hook)."""
    head = _git(repo, "rev-parse", "-q", "--verify", "HEAD").stdout.strip()
    mh = _git(repo, "rev-parse", "-q", "--verify", "MERGE_HEAD").stdout.strip()
    if not head or not mh:
        return None
    mb = _git(repo, "merge-base", head, mh).stdout.split()
    if len(mb) != 1:
        return []
    names = set(_git(repo, "diff", "--name-only", mb[0], head).stdout.split("\n")) & \
        set(_git(repo, "diff", "--name-only", mb[0], mh).stdout.split("\n"))
    out = []
    for name in sorted(n for n in names if n and (is_config_path(n) or T.is_templated(n))):
        texts = [_show(repo, f"{mb[0]}:{name}"), _show(repo, f"{head}:{name}"),
                 _show(repo, f"{mh}:{name}"), _show(repo, f":{name}")]
        if any(t is None for t in texts) or texts[1] == texts[2]:
            continue
        out.extend(audit_texts(name, *texts))
    return out


# ----------------------------------------------------------------- summary
def semantic_summary(repo, base, head, globs=None, max_changes=25):
    """Markdown: what changed *in meaning* in each config file between two revisions."""
    names = [n for n in _git(repo, "diff", "--name-only", f"{base}...{head}").stdout.split("\n") if n]
    lines, n_files = [], 0
    for name in names:
        if not (is_config_path(name) and matches(name, globs)):
            continue
        a, b = _show(repo, f"{base}:{name}"), _show(repo, f"{head}:{name}")
        fmt = F.detect(name, b or a or "")
        if a is None or b is None:
            lines.append(f"- `{name}`: {'added' if a is None else 'removed'}")
            n_files += 1
            continue
        try:
            changes = diff(F.parse(fmt, a), F.parse(fmt, b))
        except F.FormatError:
            lines.append(f"- `{name}`: changed (not structurally comparable)")
            n_files += 1
            continue
        n_files += 1
        if not changes:
            lines.append(f"- `{name}`: **formatting only** (no semantic change)")
            continue
        lines.append(f"- `{name}`: {len(changes)} semantic change(s)")
        lines.append("  ```")
        for c in changes[:max_changes]:
            lines.append("  " + c.render())
        if len(changes) > max_changes:
            lines.append(f"  ... and {len(changes) - max_changes} more")
        lines.append("  ```")
    head_line = f"### cfgmerge semantic diff ({n_files} config file(s))\n"
    return head_line + ("\n".join(lines) if lines else "_no config files changed_") + "\n"
