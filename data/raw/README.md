# Raw capture

The original candump logfile is stored as `d5175281-0a41-493a-ae0d-fb84baba6d2f.log.xz` to keep the repository compact without splitting or base64-wrapping the evidence.

Extract it before running the analyzer:

```bash
xz -dk data/raw/d5175281-0a41-493a-ae0d-fb84baba6d2f.log.xz
python3 scripts/scheiber_can_analyze.py \
  data/raw/d5175281-0a41-493a-ae0d-fb84baba6d2f.log \
  --config config/system_config.json \
  --output analysis-output
```

Uncompressed capture SHA-256: `47296d01c77acc01bc32621e8b0bbdb7c6f7e4837da1c207342baba30a281641`.
