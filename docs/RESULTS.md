# Results

Truth = the merge a human actually committed. Categories: **exact** (tree equals human), **explained** (differs only by human-made extra edits no tool could derive), **override** (equals the fact-algebra reference merge; the human deliberately chose otherwise, e.g. merge-forward flows that keep their own dependency versions), **wrong** (deviates from the reference: a real bug), **conflict** (needs a human). "Auto-resolved" = exact + explained + override.

## Held-out repos, first contact (pristine, before any fix driven by them) - v0.1.0  (2887 cases, 36 repos)

| tool | exact | explained | override | wrong | invalid | conflict | auto-resolved | silently-wrong |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| git merge-file | 2028 | 3 | 23 | 0 | 1 | 832 | **71.1%** | 0.0% |
| cfgmerge | 2193 | 27 | 107 | 2 | 0 | 558 | **80.6%** | 0.1% |

- auto-resolved gain: **+9.5 pts** (95% CI +8.3 to +10.6, paired bootstrap over cases)
- exact-match gain: **+5.7 pts** (95% CI +4.8 to +6.6)
- cfgmerge resolves cleanly where git conflicts: **285** cases; git resolves where cfgmerge conflicts: **12** cases

| format | cases | git auto-resolved | cfgmerge auto-resolved | cfgmerge silently-wrong |
|---|---:|---:|---:|---:|
| json | 1077 | 69.3% | 80.5% | 0.0% |
| yaml | 939 | 83.9% | 89.1% | 0.2% |
| xml | 466 | 62.2% | 67.6% | 0.0% |
| toml | 285 | 66.7% | 91.2% | 0.0% |
| properties | 105 | 26.7% | 33.3% | 0.0% |
| ini | 15 | 80.0% | 86.7% | 0.0% |

## Held-out repos, current code (v0.2.0; no longer a clean test set)  (2888 cases, 36 repos)

| tool | exact | explained | override | wrong | invalid | conflict | auto-resolved | silently-wrong |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| git merge-file | 2029 | 7 | 19 | 0 | 1 | 832 | **71.2%** | 0.0% |
| cfgmerge | 2197 | 73 | 56 | 0 | 0 | 562 | **80.5%** | 0.0% |

- auto-resolved gain: **+9.4 pts** (95% CI +8.2 to +10.5, paired bootstrap over cases)
- exact-match gain: **+5.8 pts** (95% CI +4.9 to +6.8)
- cfgmerge resolves cleanly where git conflicts: **281** cases; git resolves where cfgmerge conflicts: **10** cases

| format | cases | git auto-resolved | cfgmerge auto-resolved | cfgmerge silently-wrong |
|---|---:|---:|---:|---:|
| json | 1078 | 69.3% | 80.4% | 0.0% |
| yaml | 939 | 83.9% | 89.0% | 0.0% |
| xml | 466 | 62.2% | 67.6% | 0.0% |
| toml | 285 | 66.7% | 90.9% | 0.0% |
| properties | 105 | 26.7% | 34.3% | 0.0% |
| ini | 15 | 80.0% | 86.7% | 0.0% |

## Development corpus, current code (tuned on; optimistic)  (2395 cases, 23 repos)

| tool | exact | explained | override | wrong | invalid | conflict | auto-resolved | silently-wrong |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| git merge-file | 1411 | 7 | 21 | 0 | 0 | 956 | **60.1%** | 0.0% |
| cfgmerge | 1594 | 44 | 70 | 0 | 0 | 687 | **71.3%** | 0.0% |

- auto-resolved gain: **+11.2 pts** (95% CI +10.0 to +12.6, paired bootstrap over cases)
- exact-match gain: **+7.6 pts** (95% CI +6.6 to +8.8)
- cfgmerge resolves cleanly where git conflicts: **270** cases; git resolves where cfgmerge conflicts: **1** cases

| format | cases | git auto-resolved | cfgmerge auto-resolved | cfgmerge silently-wrong |
|---|---:|---:|---:|---:|
| yaml | 1450 | 61.6% | 69.6% | 0.0% |
| json | 340 | 70.0% | 85.0% | 0.0% |
| properties | 264 | 24.2% | 54.5% | 0.0% |
| toml | 259 | 78.8% | 83.4% | 0.0% |
| xml | 57 | 43.9% | 61.4% | 0.0% |
| ini | 25 | 60.0% | 60.0% | 0.0% |

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
