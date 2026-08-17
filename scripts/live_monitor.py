#!/usr/bin/env python3
"""Read-only live SocketCAN monitor with conservative Scheiber decoding.

Requires python-can. This script never calls bus.send().
"""
from __future__ import annotations
import argparse
import importlib.util
import json
import sys
import time
from pathlib import Path

try:
    import can  # type: ignore
except ImportError:
    print("python-can is required: python3 -m pip install python-can", file=sys.stderr)
    raise SystemExit(2)

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("scheiber_can_analyze", HERE / "scheiber_can_analyze.py")
if spec is None or spec.loader is None:
    raise RuntimeError("Unable to load analyzer module")
module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module
spec.loader.exec_module(module)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--channel", default="can1")
    parser.add_argument("--config", type=Path, default=HERE.parent / "config/system_config.json")
    args = parser.parse_args()
    config = json.loads(args.config.read_text(encoding="utf-8"))
    capacities = config["tanks"]
    start_ts = time.time()
    print(f"Listening read-only on {args.channel}. Press Ctrl-C to stop.")
    try:
        with can.Bus(interface="socketcan", channel=args.channel, receive_own_messages=False) as bus:
            for message in bus:
                timestamp = float(message.timestamp or time.time())
                frame = module.CandumpFrame(
                    line_number=0,
                    timestamp=timestamp,
                    interface=args.channel,
                    can_id=int(message.arbitration_id),
                    data=bytes(message.data),
                )
                decoded = module.decode_frame(frame, start_ts, capacities)
                if decoded:
                    for row in decoded:
                        print(f"{row.relative_seconds:10.3f} 0x{row.can_id} {row.name}={row.value} {row.unit} [{row.status}/{row.confidence}]")
                else:
                    print(f"{timestamp-start_ts:10.3f} 0x{frame.can_id_hex}#{frame.data_hex}")
    except KeyboardInterrupt:
        return 0
    except can.CanError as exc:
        print(f"CAN error: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
