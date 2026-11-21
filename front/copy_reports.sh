#!/bin/sh
# Copy the static reports into the built site (root vercel.json buildCommand,
# run from front/). Reports are written by the job layer (job/reports).
#
# The site no longer publishes data/: every page reads /api/v1/<dataset>,
# served by the backend project. Do not add data files here.
set -eu

DEST="${1:-dist}"
REPORTS="${REPORTS_DIR:-../job/reports}"

mkdir -p "$DEST/reports"
cp -R "$REPORTS/." "$DEST/reports/"
