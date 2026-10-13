# Results

Truth = the merge a human actually committed. Categories: **exact** (tree equals human), **explained** (differs only by human-made extra edits no tool could derive), **override** (equals the fact-algebra reference merge; the human deliberately chose otherwise, e.g. merge-forward flows that keep their own dependency versions), **wrong** (deviates from the reference: a real bug), **conflict** (needs a human). "Auto-resolved" = exact + explained + override.

## Held-out repos, first contact (pristine, before any fix driven by them)  (2887 cases, 36 repos)

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

## Held-out repos, after fixing the bugs that first run exposed  (2887 cases, 36 repos)

| tool | exact | explained | override | wrong | invalid | conflict | auto-resolved | silently-wrong |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| git merge-file | 2028 | 7 | 19 | 0 | 1 | 832 | **71.1%** | 0.0% |
| cfgmerge | 2195 | 74 | 58 | 0 | 0 | 560 | **80.6%** | 0.0% |

- auto-resolved gain: **+9.5 pts** (95% CI +8.3 to +10.6, paired bootstrap over cases)
- exact-match gain: **+5.8 pts** (95% CI +4.9 to +6.7)
- cfgmerge resolves cleanly where git conflicts: **283** cases; git resolves where cfgmerge conflicts: **10** cases

| format | cases | git auto-resolved | cfgmerge auto-resolved | cfgmerge silently-wrong |
|---|---:|---:|---:|---:|
| json | 1077 | 69.3% | 80.5% | 0.0% |
| yaml | 939 | 83.9% | 89.0% | 0.0% |
| xml | 466 | 62.2% | 67.6% | 0.0% |
| toml | 285 | 66.7% | 91.2% | 0.0% |
| properties | 105 | 26.7% | 34.3% | 0.0% |
| ini | 15 | 80.0% | 86.7% | 0.0% |

## Development corpus (tuned on; optimistic)  (2392 cases, 23 repos)

| tool | exact | explained | override | wrong | invalid | conflict | auto-resolved | silently-wrong |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| git merge-file | 1409 | 7 | 21 | 0 | 0 | 955 | **60.1%** | 0.0% |
| cfgmerge | 1591 | 46 | 71 | 1 | 0 | 683 | **71.4%** | 0.0% |

- auto-resolved gain: **+11.3 pts** (95% CI +10.1 to +12.6, paired bootstrap over cases)
- exact-match gain: **+7.6 pts** (95% CI +6.6 to +8.7)
- cfgmerge resolves cleanly where git conflicts: **272** cases; git resolves where cfgmerge conflicts: **1** cases

| format | cases | git auto-resolved | cfgmerge auto-resolved | cfgmerge silently-wrong |
|---|---:|---:|---:|---:|
| yaml | 1450 | 61.6% | 69.7% | 0.1% |
| json | 337 | 70.0% | 85.2% | 0.0% |
| properties | 264 | 24.2% | 54.5% | 0.0% |
| toml | 259 | 78.8% | 83.4% | 0.0% |
| xml | 57 | 43.9% | 61.4% | 0.0% |
| ini | 25 | 60.0% | 60.0% | 0.0% |

## How to read this honestly

**Method.** 2,887 held-out + 2,392 dev real merge commits from public repos (JSON, YAML, TOML, INI,
properties, XML). Every case is "base / ours / theirs / what the human committed". git's baseline is
`git merge-file` (the engine behind `git merge`'s content merge).

**Protocol.** 23 dev repos were used to find and fix bugs. 41 further repos were cloned afterwards and
scored without being looked at (36 produced cases). The *first-contact* table is the
unbiased number; the *after-fix* table is that same set after fixing the three bug classes it exposed
(XML identity through the single-value wrapper, word-level merge of long folded strings, the
"same item added twice differently" duplicate). It is no longer a clean test set, which is why both are shown.

**Caveats that matter.**
1. *Override.* In 2-4% of cases cfgmerge auto-resolves in the way any correct three-way merge would,
   but the human deliberately did something else (typical: a merge-forward that keeps the target
   branch's own dependency versions). git conflicts on many of these, so the human at least looks.
   For such repos use `cfgmerge learn --affinity` (suggests, and only auto-applies at >=95% over
   >=5 past merges). Offline, a strict temporal test of that idea predicted 121 of 130 confident
   conflicts correctly (93%) — but 110 of those came from one repo, so treat it as promising, not proven.
2. *Learned policy.* Identity keys / sortedness / co-changing blocks learned from file history
   made **no measurable difference** here (71.4% vs 71.4% on the dev corpus): inferring identity
   from the three versions alone already captures it. The feature stays (cheap, opt-in) but the
   evidence for "learned policy" being necessary is currently negative.
3. *Selection.* Cases are merge commits of configs changed on both sides — the cases that need a
   real merge. Repos that squash-merge contribute nothing; results describe merge-commit workflows.
4. *Truth is a human, not an oracle.* "Wrong" and "override" separate disagreement with the human
   from deviation from a reference fact-algebra merge; neither proves a merge is semantically
   right for the running system.
5. *Known gap.* When both sides rewrite a file into the same new shape and the human takes one side
   wholesale, cfgmerge can mix the two (1 dev case). A "big overlapping rewrite" guard is future work.
