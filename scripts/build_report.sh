#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

DOCS=docs
REPORT_DIR="$DOCS/report"
RAW_XZ="data/raw/d5175281-0a41-493a-ae0d-fb84baba6d2f.log.xz"
ASSEMBLED="$(mktemp /tmp/scheiber_assembled_XXXXXX.md)"
RAW_LOG="$(mktemp /tmp/scheiber_raw_XXXXXX.log)"
ANALYSIS="$(mktemp -d /tmp/scheiber_analysis_XXXXXX)"
DOCX="$DOCS/Scheiber_CAN_Engineering_Report_v1.0.docx"
PDF="$DOCS/Scheiber_CAN_Engineering_Report_v1.0.pdf"
HTML="$(mktemp /tmp/scheiber_html_XXXXXX.html)"

cleanup() {
  rm -f "$ASSEMBLED" "$RAW_LOG" "$HTML"
  rm -rf "$ANALYSIS"
}
trap cleanup EXIT

# Find suitable python3 with matplotlib
PYTHON="python3"
if [ -x "/Users/daniel/opt/anaconda3/bin/python" ]; then
  PYTHON="/Users/daniel/opt/anaconda3/bin/python"
fi

PANDOC="pandoc"
if [ -x "/Users/daniel/opt/anaconda3/bin/pandoc" ]; then
  PANDOC="/Users/daniel/opt/anaconda3/bin/pandoc"
fi

CHROME="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"

# Rebuild all generated analysis and figures from the hash-identified raw capture.
xz -dc "$RAW_XZ" > "$RAW_LOG"
"$PYTHON" scripts/scheiber_can_analyze.py "$RAW_LOG" \
  --config config/system_config.json \
  --output "$ANALYSIS"
"$PYTHON" scripts/generate_figures.py \
  --derived "$ANALYSIS" \
  --output "$DOCS/figures"

cat "$REPORT_DIR"/*.md > "$ASSEMBLED"
"$PANDOC" "$ASSEMBLED" --from=gfm+raw_html --resource-path="$DOCS:." --toc --number-sections \
  --metadata title="Scheiber CAN Analysis — Engineering Report" -o "$DOCX"
"$PANDOC" "$ASSEMBLED" --from=gfm+raw_html --resource-path="$DOCS:." --standalone --toc --number-sections \
  --metadata title="Scheiber CAN Analysis — Engineering Report" --css="$DOCS/report.css" \
  --self-contained -o "$HTML"

if command -v weasyprint >/dev/null 2>&1; then
  weasyprint "$HTML" "$PDF"
elif [ -x "$CHROME" ]; then
  "$CHROME" --headless --disable-gpu --print-to-pdf="$PDF" "$HTML" >/dev/null 2>&1
else
  printf 'Note: neither weasyprint nor Chrome found for PDF rendering; DOCX generated.\n' >&2
fi

printf 'Generated %s and %s\n' "$DOCX" "$PDF"
