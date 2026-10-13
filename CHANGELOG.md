# Changelog

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
