"""Mine real merge commits from cloned repos.

For every 2-parent merge M (parents P1, P2; base = merge-base) and every config file
changed on BOTH sides, emit a case: base / ours(P1) / theirs(P2) / truth(M, what the
human actually committed).  Output: data/cases/<repo>.jsonl
"""
import argparse
import json
import os
import subprocess
import sys
from concurrent.futures import ProcessPoolExecutor

from .. import formats as F

SKIP_NAMES = ("lock", "package-lock", "yarn.lock", "pnpm-lock", "poetry.lock", "cargo.lock",
              "go.sum", ".min.", "-lock.")
MAX_BYTES = 200_000
SUPPORTED = {"json", "yaml", "toml", "ini", "properties", "env", "xml"}
TEMPLATE_SUFFIXES = (".tpl", ".j2", ".jinja", ".jinja2", ".tmpl", ".gotmpl", ".template")


def git(repo, *args, input=None):
    return subprocess.run(["git", "-C", repo, *args], capture_output=True, text=True, input=input)


class CatFile:
    def __init__(self, repo):
        self.p = subprocess.Popen(["git", "-C", repo, "cat-file", "--batch"], stdin=subprocess.PIPE,
                                  stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)

    def get(self, spec):
        self.p.stdin.write((spec + "\n").encode())
        self.p.stdin.flush()
        header = self.p.stdout.readline().decode().split()
        if len(header) < 3 or header[1] == "missing":
            return None
        size = int(header[2])
        data = self.p.stdout.read(size)
        self.p.stdout.read(1)
        return data

    def close(self):
        self.p.stdin.close()
        self.p.wait()


def mine_repo(repo_dir, out_path, per_repo_cap=500, max_merges=6000, templates=False):
    name = os.path.basename(repo_dir)
    head = git(repo_dir, "rev-list", "--merges", f"--max-count={max_merges}", "HEAD").stdout.split()
    cf = CatFile(repo_dir)
    n = 0
    seen_triples = set()
    with open(out_path, "w") as out:
        for m in head:
            if n >= per_repo_cap:
                break
            parents = git(repo_dir, "rev-list", "--parents", "-n", "1", m).stdout.split()[1:]
            if len(parents) != 2:
                continue
            p1, p2 = parents
            r = git(repo_dir, "diff", "--name-only", p1, p2)
            files = [f for f in r.stdout.split("\n") if f]
            cands = []
            for f in files:
                base_name = os.path.basename(f).lower()
                if any(s in base_name for s in SKIP_NAMES):
                    continue
                fmt = F.detect(f, "")
                if templates:               # template files that are NOT plain-YAML config
                    if base_name.endswith(TEMPLATE_SUFFIXES):
                        cands.append((f, fmt))
                elif fmt in SUPPORTED:
                    cands.append((f, fmt))
            if not cands:
                continue
            mb = git(repo_dir, "merge-base", p1, p2).stdout.split()
            if len(mb) != 1:
                continue
            base = mb[0]
            for f, fmt in cands:
                blobs = [cf.get(f"{rev}:{f}") for rev in (base, p1, p2, m)]
                if any(b is None for b in blobs):
                    continue
                if any(len(b) > MAX_BYTES for b in blobs):
                    continue
                try:
                    b, o, t, truth = (x.decode("utf-8") for x in blobs)
                except UnicodeDecodeError:
                    continue
                if o == b or t == b or o == t:
                    continue
                key = (hash(b), hash(o), hash(t))
                if key in seen_triples:
                    continue
                seen_triples.add(key)
                out.write(json.dumps({"repo": name, "merge": m, "path": f, "fmt": fmt,
                                      "base": b, "ours": o, "theirs": t, "truth": truth}) + "\n")
                n += 1
                if n >= per_repo_cap:
                    break
    cf.close()
    return name, n


def _job(args):
    return mine_repo(*args)


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--repos", default="data/repos")
    ap.add_argument("--out", default="data/cases")
    ap.add_argument("--cap", type=int, default=500)
    ap.add_argument("-j", type=int, default=6)
    ap.add_argument("--templates", action="store_true", help="mine *.tpl/*.j2/*.tmpl files instead")
    a = ap.parse_args(argv)
    os.makedirs(a.out, exist_ok=True)
    jobs = []
    for d in sorted(os.listdir(a.repos)):
        p = os.path.join(a.repos, d)
        if os.path.isdir(os.path.join(p, ".git")):
            jobs.append((p, os.path.join(a.out, d + ".jsonl"), a.cap, 6000, a.templates))
    with ProcessPoolExecutor(a.j) as ex:
        for name, n in ex.map(_job, jobs):
            print(f"{n:5d} cases  {name}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
