# Changelog

## 0.4.0
- **pre-commit hooks** (`.pre-commit-hooks.yaml`): `cfgmerge-check`, `cfgmerge-install-driver`
  (post-checkout/post-merge/post-rewrite: git's driver config is not versioned), `cfgmerge-audit-merge`
  (pre-merge-commit).
- **GitHub Action** (`action.yml`): `check`, `diff` (semantic summary), `verify-merge` (audits the PR's
  textual merge for silently lost/broken config), with inline annotations and a job summary.
- New commands: `check`, `audit`, `summary`, `ci`; `install --quiet`.
- Non-YAML template files (`*.tpl`, `*.tmpl`, `*.gotmpl`, `*.j2`) go git-first with the guarded structural
  layer. Measured on 282 real cases: identical to git (92.2%), no regressions; no safe gain exists there.
- JSON parse errors report the real line/column.
- CI: pytest on Python 3.11-3.13 plus the Action run against the repo itself.

## 0.3.0
- Templated YAML (Helm / Go templates / Jinja, `*.yaml.j2`): template directive lines act as anchors,
  YAML between them is merged structurally with `{{ }}` expressions hidden behind placeholders.
  git stays primary (it is right ~93% of the time here); the structural result is accepted only when it is
  exactly the ideal line-fact merge and `if`/`end` blocks balance. 299 real cases: 92.6% -> 93.3%, 0 wrong.
- Items inserted from *theirs* now keep their own quoting, flow style and comments (donor nodes);
  anchored/aliased subtrees are never moved between documents.
- Benchmark: templated-file scorer, results notes split out of the generated tables.

## 0.2.0
- JSONC: JSON with comments and trailing commas is merged structurally and comments are preserved
  (span-based patcher, fuzz-tested). `.jsonc`, `.json5`, `.eslintrc`, `.babelrc` recognised.
- Whole-file-rewrite guard: if both sides rewrote most of a file in the same places, defer to plain
  textual merge instead of stitching two rewrites.
- Conflict affinity evaluated across all 64 repos with a strict temporal split
  (312/313 confident predictions correct, ~25% coverage); see docs/RESULTS.md.
- Wrong rate 0 on both corpora; auto-resolved 80.5% vs git 71.2% (held-out repos, current code).

## 0.1.0
- First release: universal semantic three-way merge, git driver, benchmark harness.
