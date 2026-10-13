from cfgmerge.engine import merge_texts
from cfgmerge import template as T

BASE = """apiVersion: apps/v1
kind: Deployment
metadata:
  name: {{ include "app.fullname" . }}
  labels:
    app: {{ .Chart.Name }}
spec:
  replicas: {{ .Values.replicas }}
  template:
    spec:
      containers:
        - name: app
          image: "{{ .Values.image.repository }}:{{ .Values.image.tag }}"
          env:
            - name: A
              value: "1"
{{- if .Values.extraEnv }}
{{ toYaml .Values.extraEnv | indent 12 }}
{{- end }}
          resources:
            limits:
              cpu: 100m
"""


def test_templated_yaml_is_unparseable_without_the_feature():
    from cfgmerge import formats as F
    import pytest
    with pytest.raises(F.FormatError):
        F.parse("yaml", BASE)


def test_adjacent_edits_git_conflicts_on_but_yaml_merges():
    from cfgmerge.bench.score import git_merge
    ours = BASE.replace("replicas: {{ .Values.replicas }}", "replicas: {{ .Values.replicaCount }}")
    theirs = BASE.replace("replicas: {{ .Values.replicas }}",
                          "replicas: {{ .Values.replicas }}\n  revisionHistoryLimit: 3")
    _, git_ok = git_merge(BASE, ours, theirs)
    assert not git_ok                                   # plain git conflicts (adjacent lines)
    o = merge_texts(BASE, ours, theirs, "templates/deployment.yaml")
    assert o.clean and o.strategy == "template"
    assert "replicaCount" in o.text and "revisionHistoryLimit: 3" in o.text
    assert o.text.count("{{- if .Values.extraEnv }}") == 1 and T.balance(o.text) == 0


def test_git_stays_primary_when_it_merges_cleanly():
    ours = BASE.replace("cpu: 100m", "cpu: 200m")
    theirs = BASE.replace("app: {{ .Chart.Name }}", "app: {{ .Chart.Name }}\n    tier: web")
    o = merge_texts(BASE, ours, theirs, "templates/deployment.yaml")
    assert o.clean and o.strategy == "textual"           # git's answer, byte for byte
    assert "cpu: 200m" in o.text and "tier: web" in o.text


def test_concurrent_appended_env_vars_union():
    ours = BASE.replace('              value: "1"\n', '              value: "1"\n            - name: B\n              value: "2"\n')
    theirs = BASE.replace('              value: "1"\n', '              value: "1"\n            - name: C\n              value: "3"\n')
    o = merge_texts(BASE, ours, theirs, "t.yaml")
    assert o.clean and "name: B" in o.text and "name: C" in o.text


def test_true_conflict_gets_markers_and_nothing_is_lost():
    ours = BASE.replace("cpu: 100m", "cpu: 200m")
    theirs = BASE.replace("cpu: 100m", "cpu: 300m")
    o = merge_texts(BASE, ours, theirs, "t.yaml")
    assert not o.clean and "<<<<<<<" in o.text and "200m" in o.text and "300m" in o.text


def test_new_template_block_added_by_one_side():
    theirs = BASE.replace("          resources:", "{{- if .Values.debug }}\n          args: [\"-v\"]\n{{- end }}\n          resources:")
    ours = BASE.replace("cpu: 100m", "cpu: 250m")
    o = merge_texts(BASE, ours, theirs, "t.yaml")
    assert o.clean and "cpu: 250m" in o.text and "{{- if .Values.debug }}" in o.text and T.balance(o.text) == 0


def test_unbalanced_result_falls_back_instead_of_emitting_it():
    assert T.balance("{{- if .a }}\nfoo\n") == 1
    assert T.balance("{{- end }}") is None
    assert T.balance("{{- if .a }}\n{{- else }}\n{{- end }}\n") == 0


def test_jinja_blocks_are_recognised():
    base = "a: 1\n{% if enabled %}\nb: {{ x }}\n{% endif %}\nc: 3\n"
    ours = base.replace("a: 1", "a: 9")
    theirs = base.replace("c: 3", "c: 7")
    o = merge_texts(base, ours, theirs, "x.yaml")
    assert o.clean and "a: 9" in o.text and "c: 7" in o.text and "{% if enabled %}" in o.text


def test_j2_suffix_detected_as_yaml():
    from cfgmerge import formats as F
    assert F.detect("config/values.yaml.j2") == "yaml"
    assert F.detect("templates/_helpers.tpl") == "text"


def test_tpl_helpers_stay_on_git_result_when_git_is_clean():
    base = '{{- define "a" -}}\nfoo\n{{- end }}\n\n{{- define "b" -}}\nbar\n{{- end }}\n'
    ours = base.replace("foo", "foo2")
    theirs = base.replace("bar", "bar2")
    o = merge_texts(base, ours, theirs, "templates/_helpers.tpl")
    assert o.clean and o.strategy == "textual" and "foo2" in o.text and "bar2" in o.text


def test_tpl_true_conflict_is_not_guessed():
    base = '{{- define "a" -}}\nfoo\n{{- end }}\n'
    o = merge_texts(base, base.replace("foo", "x"), base.replace("foo", "y"), "_helpers.tpl")
    assert not o.clean and "<<<<<<<" in o.text
