#!/usr/bin/env bash
# Deploy the static Reliability Console to GitHub Pages (legacy branch builder,
# which is reliable; the Actions deploy-pages backend was flaky 2026-07-04).
#   ./tools/replay/deploy_pages.sh
set -euo pipefail
cd "$(dirname "$0")/../.."
python3 tools/replay/build_console.py
WT=$(mktemp -d)
git worktree add "$WT" --detach -q
( cd "$WT"
  git checkout --orphan _pages -q
  git rm -rfq . 2>/dev/null || true
  cp -r "$OLDPWD"/site-console/* .
  touch .nojekyll
  git add -A
  git commit -q -m "pages: Reliability Console (static)"
  git push -f -q origin HEAD:gh-pages )
git worktree remove "$WT" --force
git worktree prune
echo "deployed -> https://vsiwach.github.io/baseten-mvp/"
