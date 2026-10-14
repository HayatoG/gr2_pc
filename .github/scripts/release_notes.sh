#!/usr/bin/env bash
# Writes the "what changed" part of the release notes (pt-BR and en-US) to stdout: every PR
# merged since the previous release, with the issues it fixes and who opened them.
#
# Each PR body carries its notes between these markers (one "- " line per change):
#   <!-- notes:pt-BR -->
#   - Corrige ... (#18)
#   <!-- /notes -->
#   <!-- notes:en-US -->
#   - Fixes ... (#18)
#   <!-- /notes -->
# A PR without the markers falls back to its title (in both sections).
# Usage: release_notes.sh <commit sha>   (needs GH_TOKEN and GH_REPO)
set -euo pipefail
sha=$1
prev=${PREV:-}; [[ -n $prev ]] || prev=$(gh release list --exclude-drafts --limit 20 --json tagName --jq '.[].tagName' | grep -vx nightly | head -1 || true)
if [[ -n $prev ]]; then
  commits=$(gh api "repos/$GH_REPO/compare/$prev...$sha" --jq '.commits[].sha')
else
  commits=$sha
fi
prs=$(for c in $commits; do gh api "repos/$GH_REPO/commits/$c/pulls" --jq '.[] | select(.merged_at != null) | .number'; done | sort -un)

block() {  # block <body> <lang>
  awk -v start="<!-- notes:$2 -->" 'index($0, start) {on=1; next} /<!-- \/notes -->/ {on=0} on && /^[[:space:]]*- / {sub(/^[[:space:]]*/, ""); print}' <<<"$1"
}
declare -A authors
pt=""; en=""
for n in $prs; do
  json=$(gh pr view "$n" --json title,body,closingIssuesReferences)
  title=$(jq -r .title <<<"$json"); body=$(jq -r '.body // ""' <<<"$json")
  p=$(block "$body" pt-BR); e=$(block "$body" en-US)
  [[ -n $p ]] || p="- $title"
  [[ -n $e ]] || e="- $title"
  pt+="${p} (PR #$n)"$'\n'; en+="${e} (PR #$n)"$'\n'
  # Issues: the ones the PR closes plus every #N its notes mention.
  for i in $(jq -r '.closingIssuesReferences[]?.number' <<<"$json") $(grep -o '#[0-9]\+' <<<"$p$e" | tr -d '#'); do
    [[ -n ${authors[$i]:-} ]] && continue
    a=$(gh api "repos/$GH_REPO/issues/$i" --jq 'select(.pull_request == null) | .user.login' 2>/dev/null || true)
    [[ -n $a ]] && authors[$i]=$a
  done
done
[[ -n $prs ]] || exit 0

thanks=""
for i in $(printf '%s\n' "${!authors[@]}" | sort -n); do thanks+="#$i (@${authors[$i]}), "; done
thanks=${thanks%, }

echo "## Novidades"
printf '%s' "$pt"
[[ -n $thanks ]] && echo && echo "Issues relatadas por: $thanks. Obrigado!"
echo
echo "## What's new"
printf '%s' "$en"
[[ -n $thanks ]] && echo && echo "Reported by: $thanks. Thank you!"
echo
