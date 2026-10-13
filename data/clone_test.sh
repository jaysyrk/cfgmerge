#!/usr/bin/env bash
cd "$(dirname "$0")" && mkdir -p repos_test && cd repos_test
clone() { r="$1"; d="${r/\//__}"; [ -d "$d/.git" ] && return; git clone --quiet --no-tags "https://github.com/$r.git" "$d" 2>&1 | tail -1; echo "done $r"; }
export -f clone
cat ../clone_test.txt | tr ' ' '\n' | xargs -P 4 -I{} bash -c 'clone {}'
echo ALL_DONE
