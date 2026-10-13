#!/usr/bin/env bash
# Real config-merge corpus: public repos with long histories of config-file merges.
cd "$(dirname "$0")/repos"
REPOS="prometheus-community/helm-charts grafana/helm-charts argoproj/argo-helm helm/charts bitnami/charts docker/awesome-compose kubernetes/examples ansible/ansible-examples fluxcd/flux2 cert-manager/cert-manager istio/istio argoproj/argo-cd traefik/traefik vuejs/core vitejs/vite babel/babel eslint/eslint prettier/prettier sveltejs/svelte denoland/deno rust-lang/cargo tokio-rs/tokio serde-rs/serde astral-sh/ruff python-poetry/poetry psf/black pypa/pip pallets/flask spring-projects/spring-boot apache/maven apache/kafka spring-projects/spring-petclinic"
clone() { r="$1"; d="${r/\//__}"; [ -d "$d/.git" ] && { echo "have $r"; return; }; git clone --quiet --no-tags "https://github.com/$r.git" "$d" 2>&1 | tail -1; echo "done $r"; }
export -f clone
echo $REPOS | tr ' ' '\n' | xargs -P 4 -I{} bash -c 'clone {}'
echo ALL_DONE
