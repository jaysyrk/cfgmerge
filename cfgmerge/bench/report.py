"""Render docs/RESULTS.md from dumped score files."""
import json
import random
import sys
from collections import Counter, defaultdict

GOOD = {"correct", "explained", "override"}


def load(path):
    return [json.loads(l) for l in open(path)]


def counts(rows, k):
    c = Counter(r[k] for r in rows)
    return c


def pct(n, d):
    return f"{100 * n / max(1, d):.1f}%"


def table(rows):
    out = ["| tool | exact | explained | override | wrong | invalid | conflict | auto-resolved | silently-wrong |",
           "|---|---:|---:|---:|---:|---:|---:|---:|---:|"]
    n = len(rows)
    for name, k in (("git merge-file", "git"), ("cfgmerge", "cfg")):
        c = counts(rows, k)
        ok = c["correct"] + c["explained"] + c["override"]
        out.append(f"| {name} | {c['correct']} | {c['explained']} | {c['override']} | {c['wrong']} | "
                   f"{c['invalid']} | {c['conflict']} | **{pct(ok, n)}** | {pct(c['wrong'] + c['invalid'], n)} |")
    return "\n".join(out)


def exact_rate(rows, k):
    return sum(r[k] == "correct" for r in rows) / max(1, len(rows))


def ok_rate(rows, k):
    return sum(r[k] in GOOD for r in rows) / max(1, len(rows))


def bootstrap(rows, fn, iters=1500, seed=7):
    rnd = random.Random(seed)
    n = len(rows)
    vals = []
    for _ in range(iters):
        s = [rows[rnd.randrange(n)] for _ in range(n)]
        vals.append(fn(s))
    vals.sort()
    return vals[int(0.025 * iters)], vals[int(0.975 * iters)]


def section(title, rows):
    n = len(rows)
    if not n:
        return f"## {title}\n\n_no cases_\n"
    d = lambda s: ok_rate(s, "cfg") - ok_rate(s, "git")
    de = lambda s: exact_rate(s, "cfg") - exact_rate(s, "git")
    lo, hi = bootstrap(rows, d)
    elo, ehi = bootstrap(rows, de)
    cross = Counter(("ok" if r["git"] in GOOD else r["git"], "ok" if r["cfg"] in GOOD else r["cfg"]) for r in rows)
    lines = [f"## {title}  ({n} cases, {len({r['repo'] for r in rows})} repos)", "", table(rows), "",
             f"- auto-resolved gain: **{100 * d(rows):+.1f} pts** (95% CI {100 * lo:+.1f} to {100 * hi:+.1f}, paired bootstrap over cases)",
             f"- exact-match gain: **{100 * de(rows):+.1f} pts** (95% CI {100 * elo:+.1f} to {100 * ehi:+.1f})",
             f"- cfgmerge resolves cleanly where git conflicts: **{cross[('conflict', 'ok')]}** cases; "
             f"git resolves where cfgmerge conflicts: **{cross[('ok', 'conflict')]}** cases", ""]
    byfmt = defaultdict(list)
    for r in rows:
        byfmt[r["fmt"]].append(r)
    lines += ["| format | cases | git auto-resolved | cfgmerge auto-resolved | cfgmerge silently-wrong |", "|---|---:|---:|---:|---:|"]
    for f, rs in sorted(byfmt.items(), key=lambda kv: -len(kv[1])):
        c = counts(rs, "cfg")
        lines.append(f"| {f} | {len(rs)} | {pct(sum(r['git'] in GOOD for r in rs), len(rs))} | "
                     f"{pct(sum(r['cfg'] in GOOD for r in rs), len(rs))} | {pct(c['wrong'] + c['invalid'], len(rs))} |")
    lines.append("")
    return "\n".join(lines)


def main():
    parts = ["# Results", "",
             "Truth = the merge a human actually committed. Categories: **exact** (tree equals human), "
             "**explained** (differs only by human-made extra edits no tool could derive), **override** "
             "(equals the fact-algebra reference merge; the human deliberately chose otherwise, e.g. "
             "merge-forward flows that keep their own dependency versions), **wrong** (deviates from the "
             "reference: a real bug), **conflict** (needs a human). \"Auto-resolved\" = exact + explained + override.", ""]
    for title, path in zip(sys.argv[1::2], sys.argv[2::2]):
        parts.append(section(title, load(path)))
    sys.stdout.write("\n".join(parts))


if __name__ == "__main__":
    main()
