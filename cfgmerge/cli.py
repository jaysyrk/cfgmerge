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
    if not a.quiet:
        print(f"installed merge driver '{DRIVER_NAME}' in {repo} (attributes: {attrs})")
    return 0


def _print_findings(findings, out=sys.stderr):
    for f in findings:
        loc = f"{f.path}:{f.line}" if f.line else f.path
        out.write(f"{loc}: {f.severity}: [{f.kind}] {f.message}\n")
        for d in f.details:
            out.write(f"    - {d}\n")


def _staged_files(repo="."):
    r = subprocess.run(["git", "-C", repo, "diff", "--cached", "--name-only", "--diff-filter=ACM"],
                       capture_output=True, text=True)
    return [p for p in r.stdout.split("\n") if p]


def cmd_check(a):
    from .check import check_files
    files = a.files or (_staged_files() if a.staged else [])
    found = check_files(files)
    _print_findings(found)
    if a.verbose or not found:
        sys.stderr.write(f"cfgmerge check: {len(files)} file(s), {len(found)} problem(s)\n")
    return 1 if any(f.severity == "error" for f in found) else 0


def cmd_audit(a):
    from .check import audit_index, audit_merge_commit
    found = audit_index() if a.index else audit_merge_commit(".", a.rev, a.paths or None)
    if found is None:
        if a.verbose:
            sys.stderr.write("cfgmerge audit: not a two-parent merge, nothing to audit\n")
        return 0
    _print_findings(found)
    if not found and a.verbose:
        sys.stderr.write("cfgmerge audit: merge result keeps everything both histories agree on\n")
    bad = any(f.severity == "error" for f in found)
    return 1 if (bad and not a.warn) else 0


def cmd_summary(a):
    from .check import semantic_summary
    sys.stdout.write(semantic_summary(".", a.base, a.head, a.paths or None))
    return 0


def cmd_ci(a):
    """Everything the GitHub Action does, in one place (also usable from any CI)."""
    from .check import audit_merge_commit, check_files, is_config_path, matches, semantic_summary
    report, findings = [], []
    base = a.base
    names = [n for n in subprocess.run(["git", "diff", "--name-only", f"{base}...{a.head}"],
                                       capture_output=True, text=True).stdout.split("\n") if n]
    cfg = [n for n in names if is_config_path(n) and matches(n, a.paths or None) and os.path.isfile(n)]
    if a.mode in ("check", "all"):
        found = check_files(cfg)
        findings += found
        report.append(f"### cfgmerge check\n{len(cfg)} config file(s) checked, **{len(found)} problem(s)**\n")
    if a.mode in ("diff", "all"):
        report.append(semantic_summary(".", base, a.head, a.paths or None))
    if a.mode in ("verify-merge", "all"):
        res = audit_merge_commit(".", a.head, a.paths or None)
        if res is None:
            report.append("### cfgmerge verify-merge\n_HEAD is not a merge commit; nothing to verify._\n")
        else:
            findings += res
            report.append(f"### cfgmerge verify-merge\n**{len(res)} problem(s)** in the textual merge of this change\n")
    for f in findings:
        loc = f"file={f.path}" + (f",line={f.line}" if f.line else "")
        msg = f.message + ("; " + "; ".join(f.details) if f.details else "")
        print(f"::{'error' if f.severity == 'error' else 'warning'} {loc},title=cfgmerge {f.kind}::{msg}")
    text = "\n".join(report)
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as fh:
            fh.write(text + "\n")
    else:
        sys.stdout.write(text + "\n")
    bad = any(f.severity == "error" for f in findings)
    return 1 if (bad and a.fail_on == "error") else 0


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
    i.add_argument("--quiet", action="store_true")
    i.add_argument("patterns", nargs="*")
    i.set_defaults(fn=cmd_install)
    c = sub.add_parser("check", help="parse + leftover-conflict-marker check (pre-commit friendly)")
    c.add_argument("files", nargs="*"), c.add_argument("--staged", action="store_true")
    c.add_argument("-v", "--verbose", action="store_true")
    c.set_defaults(fn=cmd_check)
    u = sub.add_parser("audit", help="did a merge silently lose or break config content?")
    u.add_argument("rev", nargs="?", default="HEAD")
    u.add_argument("--index", action="store_true", help="audit the staged result of an in-progress merge")
    u.add_argument("--warn", action="store_true", help="report but never fail")
    u.add_argument("--paths", nargs="*"), u.add_argument("-v", "--verbose", action="store_true")
    u.set_defaults(fn=cmd_audit)
    sm = sub.add_parser("summary", help="markdown semantic diff of config files between two revisions")
    sm.add_argument("base"), sm.add_argument("head", nargs="?", default="HEAD"), sm.add_argument("--paths", nargs="*")
    sm.set_defaults(fn=cmd_summary)
    ci = sub.add_parser("ci", help="check / semantic diff / verify-merge with GitHub annotations")
    ci.add_argument("--mode", choices=["check", "diff", "verify-merge", "all"], default="all")
    ci.add_argument("--base", required=True), ci.add_argument("--head", default="HEAD")
    ci.add_argument("--paths", nargs="*"), ci.add_argument("--fail-on", choices=["error", "never"], default="error")
    ci.set_defaults(fn=cmd_ci)
    l = sub.add_parser("learn", help="learn a merge policy from a file's git history")
    l.add_argument("file"), l.add_argument("--repo", default="."), l.add_argument("-o", "--output")
    l.add_argument("--max-versions", type=int, default=60)
    l.add_argument("--affinity", action="store_true", help="also learn how past merges resolved conflicts")
    l.set_defaults(fn=cmd_learn)
    a = ap.parse_args(argv)
    return a.fn(a)


if __name__ == "__main__":
    sys.exit(main())
