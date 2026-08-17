#!/usr/bin/env python3
"""Create dry-run NMEA 2000 translation records from a Scheiber candump log.

This utility emits JSON Lines only. It does not open a CAN interface and cannot
transmit NMEA 2000 messages. It is intended to validate instance planning and
units before implementing a real gateway.
"""
from __future__ import annotations
import argparse
import importlib.util
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("scheiber_can_analyze", HERE / "scheiber_can_analyze.py")
if spec is None or spec.loader is None:
    raise RuntimeError("Unable to load analyzer module")
mod = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = mod
spec.loader.exec_module(mod)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("log", type=Path)
    parser.add_argument("--config", type=Path, default=HERE.parent / "config/system_config.json")
    parser.add_argument("--output", type=Path, default=Path("nmea2000-dry-run.jsonl"))
    args = parser.parse_args()
    cfg = json.loads(args.config.read_text(encoding="utf-8"))
    frames = mod.parse_candump(args.log)
    t0 = frames[0].timestamp
    capacities = cfg["tanks"]
    battery_instance_by_id = {cid: i for i, cid in enumerate(sorted(mod.HOUSE_BATTERY_IDS))}
    output = []
    for frame in frames:
        if frame.can_id == 0x02040580 and len(frame.data) == 8:
            levels = [mod.u16be(frame.data, 0), mod.u16be(frame.data, 2), mod.u16be(frame.data, 4)]
            definitions = [
                (0, "water", levels[0], capacities["water_l"]),
                (1, "fuel", levels[1], capacities["diesel_1_l"]),
                (2, "fuel", levels[2], capacities["diesel_2_l"]),
            ]
            for instance, fluid, level, capacity in definitions:
                output.append({
                    "relative_seconds": round(frame.timestamp - t0, 6),
                    "pgn": 127505,
                    "name": "Fluid Level",
                    "instance": instance,
                    "fluid_type": fluid,
                    "level_percent": level,
                    "capacity_l": capacity,
                    "status": "ready-for-implementation",
                })
        elif frame.can_id in mod.HOUSE_BATTERY_IDS and len(frame.data) == 6:
            output.append({
                "relative_seconds": round(frame.timestamp - t0, 6),
                "pgn": 127508,
                "name": "Battery Status",
                "instance": battery_instance_by_id[frame.can_id],
                "voltage_v": round(mod.u16le(frame.data, 0) / 100.0, 2),
                "current_a": None,
                "temperature_k": None,
                "status": "voltage-ready; current/temperature withheld pending validation",
            })
    with args.output.open("w", encoding="utf-8") as handle:
        for row in output:
            handle.write(json.dumps(row, separators=(",", ":")) + "\n")
    print(f"Wrote {len(output)} dry-run records to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
