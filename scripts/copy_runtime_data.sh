#!/bin/sh
# Copy the static reports into a built site directory (vercel.json build).
#
# The site no longer publishes data/: every page reads /api/v1/<dataset>,
# backed by the normalized radar tables (docs/RADAR_RELATIONAL.md). data/
# stays in the repository as pipeline state only. Do not add data files here.
set -eu

DEST="${1:-dist}"

mkdir -p "$DEST/reports"
cp -R reports/. "$DEST/reports/"
