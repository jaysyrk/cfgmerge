# cfgmerge brainstorm (2026-10-12)

Goal: a **universal, schema-free, semantic three-way merge for config files**, proven against
real merge history, usable as a drop-in `git` merge driver.

## Why configs merge badly (the failure catalogue)
1. Git merges *lines*; configs are *trees*. Two people append to the same list -> conflict, though both are right.
2. Adjacent-but-independent edits conflict (delete one entry, insert another next to it).
3. Same logical change, different spelling (`30s` vs `30 sec`, `true` vs `yes`, key order) -> conflict.
4. Renames: one side renames a key, the other edits it -> edit silently lost or conflict.
5. Reordering/reformatting noise swamps real changes.
6. Clean text merges that are *semantically* wrong or even syntactically invalid (duplicate keys, broken YAML).
7. Co-changing fields (image + tag, port in two places) merged half-and-half.
8. Format traps: YAML anchors/aliases/merge keys, comments, multi-document files, TOML tables, INI sections.

## Core thesis
`merge = identity resolution + fact algebra`. Give every node a stable identity across the
three versions, then merge *facts about identities* (exists / value / position), not text.

## The decisions
| Question | Decision | Why |
|---|---|---|
| Universal how? | Format adapters -> one plain-data tree (dict/list/scalar) -> merge -> render back into the *ours* document | one algorithm, N formats |
| List identity | Infer a key (single field, dotted path, or composite) that is present + unique in every version; priors for `name`,`id`,`key`,`path`... | schema-free; no k8s `patchMergeKey` registry |
| Lists with no key | sequence merge on canonical item content with relaxed adjacency and concurrent-insert union | fixes the #1 git failure |
| Same-slot replace on both sides | conflict (never silently union) | the known "double-edit unions" gap |
| Position of inserted items | anchor to predecessor in the side that inserted it | deterministic, matches intent |
| Sorted convention | if a list/map is sorted on both sides, keep it sorted | convention-aware merge |
| Renames | detect remove+add of identical/similar value on one side, forward other side's edits | #4 |
| Semantic equality | conservative scalar normalisers, used *only* to avoid false conflicts | never silently rewrite values |
| Output fidelity | patch the `ours` round-trip document (ruamel / tomlkit / own line models) so comments + layout survive | users diff the result |
| Safety net | re-parse the output and compare to the merged tree; fall back to clean render; else conflict | never emit a wrong clean merge for a *parse-level* reason |
| Conflicts | node-granular, git-style markers + machine report with explanations | humans stay in the loop |
| Learned policy | optional: mine file history for identity keys, sortedness, atomic (co-changing) subtrees | the schema-free "learned policy" claim |
| Integration | `cfgmerge merge`, `cfgmerge git-driver`, `cfgmerge install` (repo-local, no sudo) | adoption |
| Proof | mine real merge commits from public repos; truth = the human-resolved merge; compare git vs cfgmerge; tune on dev repos, **report held-out repos** | the only claim that matters |

## Metrics (scoreboard)
Per case: `auto-correct` (clean and equals human result), `silent-wrong` (clean but differs),
`conflict`, `invalid` (output does not parse). The headline numbers are
`auto-correct rate` up and `silent-wrong rate` not above git's.

## Deliberately out of scope
- Schema-aware semantics (k8s defaults, Terraform providers): we stay schema-free.
- Executing/validating configs against live systems.
- Binary or templated (Jinja/Helm templates) files: detect and refuse, fall back to text merge.

## Stretch (only if the core is proven)
- Cross-parent subtree move detection.
- MDL "shortest explanation" semantic diff summaries.
- Mined-invariant validation of merged output.
