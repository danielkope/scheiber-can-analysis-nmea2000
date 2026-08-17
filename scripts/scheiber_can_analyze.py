#!/usr/bin/env python3
"""Analyze Scheiber proprietary extended-CAN candump captures.

The decoder is deliberately conservative. Confirmed fields are decoded normally;
hypotheses are emitted with explicit confidence and notes. The script never
transmits CAN frames.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import statistics
import sys
from collections import defaultdict
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

from scheiber_can_core import (  # noqa: E402
    GENERATOR_COMMAND_ENUM,
    HOUSE_BATTERY_IDS,
    SELECTOR_ENUM,
    CandumpFrame,
    DecodedRecord,
    parse_candump,
    u16be,
    u16le,
)
from scheiber_decoders import decode_frame  # noqa: E402

def write_csv(path: Path, rows: Iterable[Mapping[str, Any]], fieldnames: Sequence[str] | None = None) -> None:
    rows_list = list(rows)
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows_list:
        path.write_text("", encoding="utf-8")
        return
    if fieldnames is None:
        fieldnames = list(rows_list[0].keys())
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows_list)


def capture_metadata(path: Path, frames: Sequence[CandumpFrame]) -> dict[str, Any]:
    raw = path.read_bytes()
    start = datetime.fromtimestamp(frames[0].timestamp, tz=timezone.utc)
    end = datetime.fromtimestamp(frames[-1].timestamp, tz=timezone.utc)
    return {
        "source_file": path.name,
        "sha256": hashlib.sha256(raw).hexdigest(),
        "size_bytes": len(raw),
        "frame_count": len(frames),
        "unique_can_ids": len({f.can_id for f in frames}),
        "interfaces": sorted({f.interface for f in frames}),
        "start_epoch": frames[0].timestamp,
        "end_epoch": frames[-1].timestamp,
        "start_utc": start.isoformat(),
        "end_utc": end.isoformat(),
        "duration_seconds": round(frames[-1].timestamp - frames[0].timestamp, 6),
        "parse_errors": 0,
        "can_id_format": "29-bit extended IDs inferred from 8-hex-digit identifiers",
    }


def summarize(frames: Sequence[CandumpFrame], decoded: Sequence[DecodedRecord], metadata: Mapping[str, Any]) -> str:
    by_id: dict[str, list[CandumpFrame]] = defaultdict(list)
    for frame in frames:
        by_id[frame.can_id_hex].append(frame)
    tank_records = [r for r in decoded if r.category == "tank" and r.name.endswith("_level")]
    tank_latest: dict[str, Any] = {}
    for row in tank_records:
        tank_latest[row.name] = row.value
    lines = [
        "# Scheiber CAN analysis summary",
        "",
        f"- Source: `{metadata['source_file']}`",
        f"- SHA-256: `{metadata['sha256']}`",
        f"- Frames: {metadata['frame_count']}",
        f"- Unique CAN IDs: {metadata['unique_can_ids']}",
        f"- Duration: {metadata['duration_seconds']} s",
        f"- Start UTC: {metadata['start_utc']}",
        f"- End UTC: {metadata['end_utc']}",
        "",
        "## Latest tank readings in capture",
        "",
    ]
    for key in ("water_level", "diesel_1_level", "diesel_2_level"):
        lines.append(f"- {key}: {tank_latest.get(key, 'n/a')} %")
    lines.extend([
        "",
        "## Confirmed generator command mapping",
        "",
        "- `0x02460B88#01` = START",
        "- `0x02460B88#02` = STOP",
        "- Semantic decoding is confirmed; transmission/replay remains disabled pending safety validation.",
        "",
        "## Most frequent IDs",
        "",
        "| CAN ID | Frames | DLC | Unique payloads |",
        "|---|---:|---:|---:|",
    ])
    for cid, group in sorted(by_id.items(), key=lambda item: len(item[1]), reverse=True)[:20]:
        lines.append(f"| `0x{cid}` | {len(group)} | {group[0].dlc} | {len({f.data_hex for f in group})} |")
    lines.extend([
        "",
        "## Interpretation policy",
        "",
        "- `confirmed`: directly correlated with known operator state or an unambiguous physical scale.",
        "- `candidate`: strong engineering inference but needs one controlled validation run.",
        "- `guess`: useful working hypothesis only.",
        "- `unresolved`: preserved as raw data without invented semantics.",
        "",
    ])
    return "\n".join(lines)


def run(log_path: Path, output_dir: Path, config_path: Path | None = None) -> dict[str, Any]:
    config: dict[str, Any] = {
        "tanks": {"water_l": 600.0, "diesel_1_l": 500.0, "diesel_2_l": 500.0}
    }
    if config_path is not None:
        config = json.loads(config_path.read_text(encoding="utf-8"))
    capacities = config["tanks"]

    frames = parse_candump(log_path)
    start_ts = frames[0].timestamp
    decoded: list[DecodedRecord] = []
    for frame in frames:
        decoded.extend(decode_frame(frame, start_ts, capacities))

    output_dir.mkdir(parents=True, exist_ok=True)
    metadata = capture_metadata(log_path, frames)
    (output_dir / "capture_metadata.json").write_text(json.dumps(metadata, indent=2), encoding="utf-8")

    id_groups: dict[str, list[CandumpFrame]] = defaultdict(list)
    for frame in frames:
        id_groups[frame.can_id_hex].append(frame)
    inventory_rows = []
    for cid, group in sorted(id_groups.items()):
        intervals = [b.timestamp - a.timestamp for a, b in zip(group, group[1:])]
        inventory_rows.append({
            "can_id": f"0x{cid}",
            "frame_count": len(group),
            "dlc": group[0].dlc,
            "unique_payloads": len({f.data_hex for f in group}),
            "first_relative_s": round(group[0].timestamp - start_ts, 6),
            "last_relative_s": round(group[-1].timestamp - start_ts, 6),
            "median_period_s": round(statistics.median(intervals), 6) if intervals else "",
            "example_payload": group[0].data_hex,
        })
    write_csv(output_dir / "can_id_inventory.csv", inventory_rows)

    decoded_rows = [asdict(row) for row in decoded]
    write_csv(output_dir / "decoded_fields_long.csv", decoded_rows)
    write_csv(output_dir / "tank_samples.csv", [r for r in decoded_rows if r["category"] == "tank"])
    write_csv(output_dir / "house_battery_candidates.csv", [r for r in decoded_rows if r["category"] == "house_battery"])
    write_csv(output_dir / "charger_candidates.csv", [r for r in decoded_rows if r["category"] == "charger"])
    write_csv(output_dir / "event_candidates.csv", [r for r in decoded_rows if r["category"] in {"panel", "generator"}])

    (output_dir / "summary.md").write_text(summarize(frames, decoded, metadata), encoding="utf-8")
    return {"metadata": metadata, "decoded_count": len(decoded), "output_dir": str(output_dir)}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("log", type=Path, help="candump log in '(timestamp) canX ID#DATA' format")
    parser.add_argument("--output", type=Path, default=Path("analysis-output"), help="directory for CSV/JSON/Markdown results")
    parser.add_argument("--config", type=Path, default=None, help="optional system_config.json")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        result = run(args.log, args.output, args.config)
    except (OSError, ValueError, KeyError, json.JSONDecodeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
