#!/bin/sh
# Copy the public runtime data and static reports into a built site directory.
# Used by both .github/workflows/deploy-pages.yml (GitHub Pages) and
# vercel.json (Vercel). Keep this list as the single allow-list of what is
# published from data/: anything not named here stays out of the site.
set -eu

DEST="${1:-dist}"

mkdir -p "$DEST/reports"
cp -R reports/. "$DEST/reports/"

mkdir -p "$DEST/data"
cp data/public-theme-ranking-v0.8.json "$DEST/data/"
cp data/public-theme-momentum-latest-v0.9.json "$DEST/data/"
cp data/public-theme-momentum-history-v0.9.json "$DEST/data/"
cp data/public-stock-watchlist-v1.json "$DEST/data/"
cp data/stock-audit-latest.json "$DEST/data/"
cp data/theme-events.json "$DEST/data/"
cp data/source-status.json "$DEST/data/"
cp data/waytoagi-7d.json "$DEST/data/"
cp data/institutional-rankings.json "$DEST/data/"
cp data/institutional-flows.json "$DEST/data/"
cp data/fundamentals-index.json "$DEST/data/"
# Pre-market board. Guarded because a deploy may land before the pre-market job
# has ever produced the file. Also the API's fallback when the DB path fails.
if [ -f data/pre-market-latest.json ]; then cp data/pre-market-latest.json "$DEST/data/"; fi
cp -R data/fundamentals "$DEST/data/"
if [ -f data/broker-stats.json ]; then cp data/broker-stats.json "$DEST/data/"; fi
if [ -f data/broker-coverage.json ]; then cp data/broker-coverage.json "$DEST/data/"; fi
if [ -d data/broker-map ]; then cp -R data/broker-map "$DEST/data/"; fi
