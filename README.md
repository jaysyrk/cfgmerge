# cfgmerge

**Universal, schema-free, semantic three-way merge for config files** — a drop-in `git` merge driver.

Git merges *lines*. Configs are *trees*. Two people append to the same list, edit neighbouring
keys, or reformat a file and git conflicts (or worse, merges into something invalid).
cfgmerge parses both sides into a tree, resolves *identity* (which item is which), merges
facts per identity, writes the result back **into your original document** (comments and
layout kept), and re-parses its own output to prove it before handing it over.

```
git merge feature        # with cfgmerge installed: concurrent edits merge, real conflicts get markers
```

## Formats
JSON · YAML (incl. multi-document, anchors via expansion) · TOML · INI · `.properties` · `.env` ·
XML (pom.xml, web.xml…) · templated YAML (Helm/Go-template/Jinja, `*.yaml.j2`) · JSON with comments / trailing commas (tsconfig, eslintrc; comments preserved) · plain-text lists (`requirements.txt`, `.gitignore`). Anything that
fails to parse falls back to a plain `git merge-file` merge, so it is never worse than git on
unparseable input.

## Use it
```bash
pip install git+https://github.com/jaysyrk/cfgmerge     # or a wheel from the Releases page
cfgmerge merge BASE OURS THEIRS -o MERGED     # exit 0 clean, 1 conflicts (markers written)
cfgmerge diff old.yaml new.yaml               # semantic diff, ignores formatting/order noise
cfgmerge install                              # register as git merge driver in this repo (no sudo)
cfgmerge learn values.yaml -o .cfgmerge.json  # learn identity keys / sort order / co-changing blocks
cfgmerge learn values.yaml --affinity -o .cfgmerge.json   # + how past merges resolved conflicts here
cfgmerge merge B O T --policy .cfgmerge.json --auto-affinity  # auto-apply only at >=95% over >=5 merges
```
`install` only edits `.git/config` and `.git/info/attributes` of the repo you run it in.
Add `--committed` to write `.gitattributes` instead (team-wide), and set
`git config merge.cfgmerge.driver "cfgmerge git-driver %O %A %B %L %P"` once per clone.

## How it works
| Step | What |
|---|---|
| 1 | Detect format; textual fast paths (nothing changed / one side only → byte-exact result) |
| 2 | Parse base/ours/theirs to plain data |
| 3 | **Identity**: map keys; list items by an *inferred* key (single field, dotted path, or ≤3-field composite) — no schema |
| 4 | **Merge facts per identity**; concurrent inserts union; replacing the same slot differently conflicts |
| 5 | Renames detected (map keys and list-item identity fields) so edits and deletes meet instead of passing silently |
| 6 | Multi-line strings merge line-wise (strictly, like git); scalar equivalence (`30s` = `30 sec`) only to avoid false conflicts |
| 7 | Render *into ours* (comments, quotes, indent preserved), **re-parse and verify**, else fresh render, else textual fallback |
| 8 | Conflicts: node-granular, git-style markers + a machine-readable report with the reason |

## Honest evaluation
Truth is the merge a human actually committed in public repositories (5,279 real merge cases,
JSON/YAML/TOML/INI/properties/XML). On **41 held-out repos never inspected during development**:

| | git merge-file | cfgmerge |
|---|---:|---:|
| auto-resolved (first contact, 2,887 cases) | 71.1% | **80.6%** (+9.5 pts, 95% CI +8.3 to +10.6) |
| silently wrong | 0.0% (1 invalid file) | 0.1% on first contact (2 cases, fixed), 0.0% since |

cfgmerge resolved 283 merges where git conflicted and regressed on 10 where git succeeded.
Opt-in *conflict affinity* (learn how past merges of a path were resolved): 312 of 313 confident
predictions correct under a strict temporal split, 25% coverage, concentrated in repos with a stable
merge-forward convention.
Full tables are in [`docs/RESULTS.md`](docs/RESULTS.md); protocol, affinity evaluation and caveats
(override cases, learned policy had no measurable effect) in [`docs/RESULTS_NOTES.md`](docs/RESULTS_NOTES.md). Reproduce: `data/clone.sh`, then
`python -m cfgmerge.bench.mine && python -m cfgmerge.bench.score`.

## Limits (read these)
- **Auto-merged ≠ blessed.** Where a human intentionally overrides one side's change (merge-forward
  flows that keep their own dependency versions), any correct three-way merge, git included,
  would take the other side. cfgmerge reports those as "override" in the benchmark; use the
  conflict-affinity features or review the diff.
- **Templated YAML (Helm / Go templates / Jinja)**: git's line merge is already right on ~93% of these,
  so it stays primary. A template-aware layer (directive lines as anchors, YAML merged between them,
  accepted only if the result is exactly the ideal line-fact merge with balanced `if`/`end`) resolves
  a few extra conflicts. Measured gain is small: +2 of 22 git conflicts, 0 regressions, on 299 real cases.
- When both sides rewrite most of a file in the same places, cfgmerge defers to a plain textual merge
  (a tree merge of two independent rewrites isn't trustworthy).
- YAML anchors/aliases are expanded for the merge; the result is verified but anchors you edit
  through may be re-emitted expanded.
- No schema awareness (e.g. Kubernetes defaults); identity is inferred from the data.

## Layout
`cfgmerge/{seqmerge,merge,identity,equiv,policy,learn,formats,xmlfmt,engine,diff,cli}.py` ·
benchmark `cfgmerge/bench/{mine,score,why,inspect}.py` · tests `tests/`.
