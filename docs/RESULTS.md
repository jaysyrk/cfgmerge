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

## Held-out repos, current code (not a clean test set any more)  (2888 cases, 36 repos)

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

## Templated YAML (Helm / Go templates / Jinja) - files that are not valid YAML

These files were previously *invisible* to the benchmark (unparseable, so skipped). 299 real merge
cases across 14 repos (grafana/helm-charts, istio, cert-manager, bitnami/charts, elastic, ...).
Judging is textual: **exact** = equals the human's file; **reference** = same lines as the ideal
line-fact merge; **broken** = unbalanced `if`/`end`.

```
templated, unparseable-as-YAML merge cases: 299   repos: 14
                      exact  reference      wrong     broken   conflict  auto-ok%   bad%
git merge-file          276          1          0          0         22     92.6%   0.0%
cfgmerge                277          2          0          0         20     93.3%   0.0%

git x cfgmerge: {('ok', 'ok'): 277, ('conflict', 'conflict'): 20, ('conflict', 'ok'): 2}
strategies used: {'textual': 297, 'template': 2}
```

Design, and why it is modest: git's line merge is *already* right on 92.6% of these with zero
wrong results, so git stays primary. The structural layer (`cfgmerge/template.py`) only runs where
git conflicts, and its result is accepted only if it is exactly the ideal line-fact merge (nothing
invented, duplicated or re-indented) with `if`/`end` blocks balanced. An earlier, more ambitious
version made 15 wrong merges on this corpus (YAML re-rendering drifted quoting/indent and
duplicated a key); the post-condition exists because of that. Net gain: **+2 of 22 git conflicts
resolved, 0 regressions**. Templated files are a place where being never worse than git is the
achievement, not a large improvement.

---
Affinity evaluation, protocol and caveats: see [RESULTS_NOTES.md](RESULTS_NOTES.md).
