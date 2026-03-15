#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
BACKEND_DIR="$ROOT_DIR/backend"
FRONTEND_DIR="$ROOT_DIR/frontend"

# GitHub Pages repo name — used as basePath so assets resolve correctly.
# Change this if your repo has a different name.
REPO_NAME="black-swan-events"

echo "=== Black Swan Analytics — Update & Deploy ==="
echo ""

# ── Step 1: Activate venv and run data collection ────────────────────────
echo "▸ Step 1: Collecting new market data..."
cd "$BACKEND_DIR"
source venv/bin/activate 2>/dev/null || {
  echo "  Creating virtual environment..."
  python3 -m venv venv
  source venv/bin/activate
  pip install -q -r requirements.txt
}

# Run incremental collection + enrichment
python3 -c "
import asyncio, os, sys
sys.path.insert(0, '.')
from collector import run_full_collection, run_black_swan_enrichment

async def main():
    result = await run_full_collection()
    print(f'  Collection: {result}')
    api_key = os.environ.get('GEMINI_API_KEY', '')
    enrichment = await run_black_swan_enrichment(api_key or None)
    print(f'  Enrichment: {enrichment}')

asyncio.run(main())
"
echo "  ✓ Data collection complete"
echo ""

# ── Step 2: Export data to static JSON ───────────────────────────────────
echo "▸ Step 2: Exporting data to static JSON..."
python3 "$SCRIPT_DIR/export_data.py"
echo "  ✓ Export complete"
echo ""

# ── Step 3: Build static frontend ───────────────────────────────────────
echo "▸ Step 3: Building static frontend..."
cd "$FRONTEND_DIR"
NEXT_PUBLIC_STATIC=true NEXT_PUBLIC_BASE_PATH="/$REPO_NAME" npm run build
echo "  ✓ Build complete"
echo ""

# ── Step 4: Deploy to GitHub Pages ──────────────────────────────────────
echo "▸ Step 4: Deploying to GitHub Pages..."
cd "$ROOT_DIR"

DEPLOY_DIR=$(mktemp -d)
cp -r "$FRONTEND_DIR/out/." "$DEPLOY_DIR/"
touch "$DEPLOY_DIR/.nojekyll"

cd "$DEPLOY_DIR"
git init -q
git checkout -q -b gh-pages
git add -A
git commit -q -m "Deploy $(date -u '+%Y-%m-%d %H:%M') UTC"

REMOTE_URL=$(cd "$ROOT_DIR" && git remote get-url origin 2>/dev/null || echo "")
if [ -z "$REMOTE_URL" ]; then
  echo "  ⚠ No git remote found. Skipping push."
  echo "  Set up with: git remote add origin <your-repo-url>"
  echo "  Then run: cd $DEPLOY_DIR && git push --force origin gh-pages"
else
  git remote add origin "$REMOTE_URL"
  git push --force origin gh-pages
  echo "  ✓ Deployed to GitHub Pages"
fi

rm -rf "$DEPLOY_DIR"
echo ""
echo "=== Done! ==="
