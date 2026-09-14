#!/usr/bin/env bash
# Refresh data and publish the static dashboard to GitHub Pages.
#
#   ./scripts/update_and_deploy.sh            # pipeline + build + deploy
#   SKIP_PIPELINE=1 ./scripts/update_and_deploy.sh   # rebuild/deploy existing data
#   SKIP_DEPLOY=1 ./scripts/update_and_deploy.sh     # everything except the push
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
BACKEND_DIR="$ROOT_DIR/backend"
FRONTEND_DIR="$ROOT_DIR/frontend"
REPO_NAME="$(basename -s .git "$(git -C "$ROOT_DIR" remote get-url origin)")"

command -v uv >/dev/null || { echo "uv is required: https://docs.astral.sh/uv/"; exit 1; }

echo "▸ Pipeline"
cd "$BACKEND_DIR"
uv sync --frozen
if [[ -z "${SKIP_PIPELINE:-}" ]]; then
  uv run python cli.py run        # collect → score → depth → headlines → export
else
  uv run python cli.py export
fi

echo "▸ Tests"
uv run pytest -q
(cd "$FRONTEND_DIR" && npm ci && npm test)

echo "▸ Static build (basePath=/$REPO_NAME)"
cd "$FRONTEND_DIR"
rm -rf out
NEXT_PUBLIC_STATIC=true NEXT_PUBLIC_BASE_PATH="/$REPO_NAME" npm run build
test -s out/data/stats-10.json || { echo "Export missing from build output"; exit 1; }

if [[ -n "${SKIP_DEPLOY:-}" ]]; then
  echo "SKIP_DEPLOY set; build is in frontend/out"
  exit 0
fi

echo "▸ Deploy to gh-pages"
DEPLOY_DIR="$(mktemp -d)"
trap 'rm -rf "$DEPLOY_DIR"' EXIT
cp -R out/. "$DEPLOY_DIR/"
touch "$DEPLOY_DIR/.nojekyll"
cd "$DEPLOY_DIR"
git init -q -b gh-pages
git add -A
git commit -q -m "Deploy $(date -u '+%Y-%m-%d %H:%M') UTC"
git push --force "$(git -C "$ROOT_DIR" remote get-url origin)" gh-pages
echo "✓ Deployed"
