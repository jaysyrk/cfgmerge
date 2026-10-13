"""cfgmerge command line + git merge driver."""
import argparse
import os
import subprocess
import sys

from . import formats as F
from .diff import diff
from .engine import merge_texts
from .policy import EMPTY, Policy

DRIVER_NAME = "cfgmerge"
DEFAULT_PATTERNS = ["*.yaml", "*.yml", "*.json", "*.toml", "*.ini", "*.cfg", "*.properties",
                    ".env", ".env.*", "*.xml", "requirements*.txt", ".gitignore"]


def _read(path):
    try:
        with open(path, encoding="utf-8") as f:
            return f.read()
    except FileNotFoundError:
        return ""


def _policy(path):
    if path and os.path.exists(path):
        return Policy.from_json(_read(path))
    return EMPTY


def cmd_merge(a):
    base, ours, theirs = _read(a.base), _read(a.ours), _read(a.theirs)
    out = merge_texts(base, ours, theirs, a.path or a.ours, a.format, _policy(a.policy),
                      base_missing=not os.path.exists(a.base), auto_affinity=a.auto_affinity)
    if a.output:
        with open(a.output, "w", encoding="utf-8") as f:
            f.write(out.text)
    else:
        sys.stdout.write(out.text)
    if a.verbose or not out.clean:
        sys.stderr.write(f"cfgmerge: {out.fmt} via {out.strategy}; "
                         + ("clean" if out.clean else f"{len(out.conflicts)} conflict(s)") + "\n")
        for c in out.conflicts:
            hint = f"  (history suggests {c.suggestion}, {c.confidence:.0%})" if c.suggestion else ""
            sys.stderr.write(f"  ! {c.where()}  [{c.kind}] {c.note}{hint}\n")
        if a.verbose:
            for kind, p in out.notes:
                sys.stderr.write(f"  . {kind}: {p}\n")
    return 0 if out.clean else 1


def cmd_git_driver(a):
    """git calls:  cfgmerge git-driver %O %A %B %L %P   (result is written over %A)"""
    base, ours, theirs = _read(a.base), _read(a.ours), _read(a.theirs)
    pol = os.path.join(os.path.dirname(os.path.abspath(a.path)) if a.path else ".", ".cfgmerge.json")
    out = merge_texts(base, ours, theirs, a.path or a.ours, None, _policy(pol if os.path.exists(pol) else None),
                      base_missing=(base == ""))
    with open(a.ours, "w", encoding="utf-8") as f:
        f.write(out.text)
    return 0 if out.clean else 1


def cmd_diff(a):
    ta, tb = _read(a.a), _read(a.b)
    fmt = a.format or F.detect(a.b, tb)
    changes = diff(F.parse(fmt, ta), F.parse(fmt, tb))
    for c in changes:
        print(c.render())
    if not changes:
        print("no semantic changes")
    return 0


def cmd_install(a):
    repo = a.repo
    exe = a.exe or f"{sys.executable} -m cfgmerge"
    cfg = lambda *x: subprocess.run(["git", "-C", repo, "config", "--local", *x], check=True)
    cfg(f"merge.{DRIVER_NAME}.name", "cfgmerge semantic config merge")
    cfg(f"merge.{DRIVER_NAME}.driver", f"{exe} git-driver %O %A %B %L %P")
    attrs = os.path.join(repo, ".git", "info", "attributes") if not a.committed else os.path.join(repo, ".gitattributes")
    os.makedirs(os.path.dirname(attrs), exist_ok=True)
    existing = _read(attrs)
    lines = [f"{p} merge={DRIVER_NAME}" for p in (a.patterns or DEFAULT_PATTERNS)]
    new = [l for l in lines if l not in existing]
    with open(attrs, "a", encoding="utf-8") as f:
        if existing and not existing.endswith("\n"):
            f.write("\n")
        f.write("\n".join(new) + ("\n" if new else ""))
    print(f"installed merge driver '{DRIVER_NAME}' in {repo} (attributes: {attrs})")
    return 0


def cmd_learn(a):
    from .learn import learn_from_git
    pol = learn_from_git(a.repo, a.file, max_versions=a.max_versions, affinity=a.affinity)
    text = pol.to_json()
    if a.output:
        with open(a.output, "w") as f:
            f.write(text + "\n")
    else:
        print(text)
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(prog="cfgmerge", description="universal semantic merge for config files")
    sub = ap.add_subparsers(dest="cmd", required=True)
    m = sub.add_parser("merge", help="three-way merge BASE OURS THEIRS")
    m.add_argument("base"), m.add_argument("ours"), m.add_argument("theirs")
    m.add_argument("-o", "--output"), m.add_argument("--path"), m.add_argument("--format")
    m.add_argument("--policy"), m.add_argument("-v", "--verbose", action="store_true")
    m.add_argument("--auto-affinity", action="store_true",
                   help="auto-resolve conflicts the policy's merge history decides (>=5 merges, >=95%%)")
    m.set_defaults(fn=cmd_merge)
    g = sub.add_parser("git-driver", help="entry point for git's merge driver")
    g.add_argument("base"), g.add_argument("ours"), g.add_argument("theirs")
    g.add_argument("marker", nargs="?"), g.add_argument("path", nargs="?")
    g.set_defaults(fn=cmd_git_driver)
    d = sub.add_parser("diff", help="semantic diff of two files")
    d.add_argument("a"), d.add_argument("b"), d.add_argument("--format")
    d.set_defaults(fn=cmd_diff)
    i = sub.add_parser("install", help="register cfgmerge as git merge driver in a repo (no sudo)")
    i.add_argument("--repo", default="."), i.add_argument("--exe")
    i.add_argument("--committed", action="store_true", help="write .gitattributes instead of .git/info/attributes")
    i.add_argument("patterns", nargs="*")
    i.set_defaults(fn=cmd_install)
    l = sub.add_parser("learn", help="learn a merge policy from a file's git history")
    l.add_argument("file"), l.add_argument("--repo", default="."), l.add_argument("-o", "--output")
    l.add_argument("--max-versions", type=int, default=60)
    l.add_argument("--affinity", action="store_true", help="also learn how past merges resolved conflicts")
    l.set_defaults(fn=cmd_learn)
    a = ap.parse_args(argv)
    return a.fn(a)


if __name__ == "__main__":
    sys.exit(main())
