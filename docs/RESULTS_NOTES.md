# Results notes (static; the generated tables are in RESULTS.md)

## Conflict affinity (opt-in): does history predict how a conflict gets resolved?

Strict temporal protocol over **all 64 repos**: a conflict is predicted only from *older* merges of the
same file and path, and only when the policy would actually auto-apply (>= 5 older observations,
>= 95% agreeing, never "novel"). Thresholds were fixed before this run.

```
conflicts seen: 1266   auto-applicable predictions: 313   correct: 312   precision: 99.7%   coverage: 24.7%
expressjs/express 110/110 - spring-boot 96/96 - spring-framework 57/57 - webpack 45/45 - prettier 4/4 - typescript-eslint 0/1
(30 repos produced no confident prediction)
```
Reproduce: `python -m cfgmerge.bench.affinity_eval`. Read it as: where a repo has a *stable merge-forward
convention* (keep the target branch's value), affinity captures it almost perfectly; elsewhere it
abstains. Predictions come from 6 repos, so the claim is "works where conventions exist", not "works everywhere".

## How to read this honestly

**Method.** ~5,300 real merge commits from public repos (JSON, YAML, TOML, INI, properties, XML), each
"base / ours / theirs / what the human committed". git's baseline is `git merge-file`.

**Protocol.** 23 dev repos were used to find and fix bugs. 41 further repos were cloned afterwards and
scored without being looked at (36 produced cases). The *first-contact* table is the unbiased
number; the later tables are the same repos after fixing what they exposed, so they are not clean test sets.

**Caveats that matter.**
1. *Override.* In ~2-4% of cases cfgmerge auto-resolves the way any correct three-way merge would, but
   the human deliberately did something else (typically a merge-forward that keeps the target branch's
   own dependency versions). git conflicts on many of these, so a human at least looks. Affinity
   (above) is the targeted remedy.
2. *Learned policy.* Identity keys / sortedness / co-changing blocks learned from file history made
   **no measurable difference** (71.4% vs 71.4% on the dev corpus): inferring identity from the three
   versions already captures it.
3. *Selection.* Cases are merge commits of configs changed on both sides. Squash-merge repos contribute
   nothing; results describe merge-commit workflows.
4. *Truth is a human, not an oracle.* "Wrong" and "override" separate disagreement with the human from
   deviation from a reference fact-algebra merge; neither proves a merge is right for a running system.
5. *Rewrites.* When both sides rewrite most of a file in largely the same places, cfgmerge defers to
   plain textual merge rather than stitching two rewrites together (cost: ~0.1 pt of auto-resolution).

## Non-YAML templates (`*.tpl`, `*.tmpl`, `*.gotmpl`, `*.j2`)

282 real merge cases from 10 repos (Helm `_helpers.tpl` / `_pod.tpl`, Traefik Go templates, ...):

```
git merge-file   exact=258 reference=2 wrong=0 broken=0 conflict=22   auto-ok=92.2%
cfgmerge         exact=258 reference=2 wrong=0 broken=0 conflict=22   auto-ok=92.2%
```
**No gain, no harm.** The 22 conflicts are genuine overlapping edits. The tempting shortcut, a relaxed line
merge (adjacent edits independent, concurrent inserts unioned), resolved 4 of the 13 dev-set conflicts and was
*wrong in 2 of those 4*: precisely why the structural layer only ever acts behind the line-fact post-condition
(see `cfgmerge/template.py`) and why nothing passed it here.

## Pre-commit hooks and the Action

Verified end to end rather than assumed: the three hooks were installed with the real `pre-commit` tool from a
local checkout (check fails on a broken file with the right line; post-checkout registers the driver;
pre-merge-commit audit runs and passes a clean merge), and the Action ran on GitHub's runners both on a clean
PR (green) and on a deliberately broken one (red, with inline annotations on the exact files).
