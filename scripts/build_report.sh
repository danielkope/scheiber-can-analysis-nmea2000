#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

DOCS=docs
REPORT_DIR="$DOCS/report"
RAW_XZ="data/raw/d5175281-0a41-493a-ae0d-fb84baba6d2f.log.xz"
ASSEMBLED="$(mktemp --suffix=.md)"
RAW_LOG="$(mktemp --suffix=.log)"
ANALYSIS="$(mktemp -d)"
DOCX="$DOCS/Scheiber_CAN_Engineering_Report_v1.0.docx"
PDF="$DOCS/Scheiber_CAN_Engineering_Report_v1.0.pdf"
HTML="$(mktemp --suffix=.html)"

cleanup() {
  rm -f "$ASSEMBLED" "$RAW_LOG" "$HTML"
  rm -rf "$ANALYSIS"
}
trap cleanup EXIT

for command_name in python3 xz pandoc weasyprint; do
  command -v "$command_name" >/dev/null 2>&1 || {
    printf 'Missing required command: %s\n' "$command_name" >&2
    exit 2
  }
done

# Rebuild all generated analysis and figures from the hash-identified raw capture.
xz -dc "$RAW_XZ" > "$RAW_LOG"
python3 scripts/scheiber_can_analyze.py "$RAW_LOG" \
  --config config/system_config.json \
  --output "$ANALYSIS"
python3 scripts/generate_figures.py \
  --derived "$ANALYSIS" \
  --output "$DOCS/figures"

cat "$REPORT_DIR"/*.md > "$ASSEMBLED"
pandoc "$ASSEMBLED" --from=gfm+raw_html --resource-path="$DOCS:." --toc --number-sections \
  --metadata title="Scheiber CAN Analysis — Engineering Report" -o "$DOCX"
pandoc "$ASSEMBLED" --from=gfm+raw_html --resource-path="$DOCS:." --standalone --toc --number-sections \
  --metadata title="Scheiber CAN Analysis — Engineering Report" --css="$DOCS/report.css" \
  --embed-resources -o "$HTML"
weasyprint "$HTML" "$PDF"
printf 'Generated %s and %s\n' "$DOCX" "$PDF"
