#!/usr/bin/env python3
"""Decoder and cautious live tooling for the observed Scheiber Multibloc V8 10-function panel.

The offline decoder uses only the Python standard library. Live SocketCAN monitoring/
transmission requires python-can (already an optional project dependency).

Active control is intentionally explicit: --press and --query-states require --transmit.
The captured physical panel shows momentary press/release events; they are not ON/OFF
commands. Callers that want a desired-state API must synchronize actual output state first.
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass
import json
import re
import sys
import time
from pathlib import Path
from typing import Iterable, Optional

PANEL_BASE = 0x1808
ALIVE_ID = 0x00001808
ANALOG_ID = 0x02041808
DIGITAL_INPUT_ID = 0x02141808
STATE_IDS = [0x02161808, 0x02181808, 0x021A1808, 0x021C1808, 0x021E1808, 0x02201808]
SWITCH_ID = 0x04001808
SYNC_ID = 0x04081808
LED_CMD_ID = 0x04020000

OUTPUT_NAMES = {
    1: "electronics",
    2: "deck_floodlight",
    3: "navigation_lights",
    4: "anchor_light",
    5: "steaming_light",
    6: "bilge_port_auto",
    7: "bilge_port_manual",
    8: "bilge_starboard_auto",
    9: "bilge_starboard_manual",
    10: "fresh_water_pump_enabled",
    11: "fridge_unit",
    12: "lighting",
}

KEY_NAMES = {
    0x02: "electronics",
    0x03: "navigation_lights",
    0x04: "steaming_light",
    0x05: "deck_floodlight",
    0x06: "anchor_light",
    0x07: "lighting",
    0x08: "bilge_port_auto",
    0x09: "bilge_starboard_auto",
    0x0A: "fresh_water_pump",
    0x0B: "fridge_unit",
    0x0C: "bilge_port_manual",
    0x0D: "bilge_starboard_manual",
}
NAME_TO_KEY = {v: k for k, v in KEY_NAMES.items()}

DIGITAL_INPUT_BITS = {
    0: "fresh_water_pump_running",
    1: "bilge_port_running",
    2: "bilge_starboard_running",
}

CANDUMP_RE = re.compile(
    r"^\s*\((?P<ts>[0-9.]+)\)\s+(?P<iface>\S+)\s+(?P<canid>[0-9A-Fa-f]{3,8})#(?P<data>[0-9A-Fa-f]*)\s*$"
)

@dataclass(frozen=True)
class Frame:
    timestamp: Optional[float]
    interface: Optional[str]
    can_id: int
    data: bytes


def parse_candump_line(line: str) -> Optional[Frame]:
    m = CANDUMP_RE.match(line)
    if not m:
        return None
    return Frame(
        timestamp=float(m.group("ts")),
        interface=m.group("iface"),
        can_id=int(m.group("canid"), 16),
        data=bytes.fromhex(m.group("data")),
    )


def multibloc_id_fields(can_id: int) -> dict:
    return {
        "frame_type": (can_id & 0x1FFE0000) >> 17,
        "reference": (can_id & 0x0001FF80) >> 7,
        "coding": (can_id & 0x00000078) >> 3,
        "subnetwork": can_id & 0x7,
    }


def decode_frame(frame: Frame) -> list[dict]:
    can_id = frame.can_id
    data = frame.data
    out: list[dict] = []

    if can_id == ALIVE_ID and len(data) >= 5:
        out.append({
            "kind": "alive",
            "firmware": f"{data[0]:02d}.{data[1]:02d}.{data[2]:02d}",
            "configuration_crc": f"0x{(data[3] << 8 | data[4]):04X}",
            "multibloc": multibloc_id_fields(can_id),
        })
        return out

    if can_id == SWITCH_ID and len(data) == 5:
        switch_device_id = int.from_bytes(data[:4], "big")
        code = data[4]
        key = code & 0x7F
        out.append({
            "kind": "switch",
            "switch_device_id": f"0x{switch_device_id:08X}",
            "key": key,
            "key_hex": f"0x{key:02X}",
            "name": KEY_NAMES.get(key, "unknown"),
            "action": "press" if code & 0x80 else "release",
            "raw_code": f"0x{code:02X}",
        })
        return out

    if can_id in STATE_IDS and len(data) >= 8:
        group = STATE_IDS.index(can_id)
        first_output = group * 2 + 1
        # Domoticz MultiblocV8 reads command-state bit 0 from byte 2 / byte 6,
        # level from byte 0 / byte 4, and blink bit 1 from the same flag bytes.
        for output, level_byte, flags_byte in (
            (first_output, 0, 2),
            (first_output + 1, 4, 6),
        ):
            flags = data[flags_byte]
            out.append({
                "kind": "output_state",
                "output": output,
                "name": OUTPUT_NAMES.get(output, "unknown"),
                "on": bool(flags & 0x01),
                "blink": bool(flags & 0x02),
                "level_raw": data[level_byte],
                "flags_raw": flags,
                "state_can_id": f"0x{can_id:08X}",
            })
        return out

    if can_id == DIGITAL_INPUT_ID and data:
        value = data[0]
        out.append({
            "kind": "digital_inputs",
            "raw": value,
            "raw_hex": f"0x{value:02X}",
            "signals": {name: bool(value & (1 << bit)) for bit, name in DIGITAL_INPUT_BITS.items()},
            "note": "bit-to-function mapping is inferred from controlled tests; frame class E_TOR is source-derived",
        })
        return out

    if can_id == SYNC_ID:
        out.append({"kind": "sfsp_sync", "data_hex": data.hex().upper()})
        return out

    if can_id == LED_CMD_ID:
        out.append({"kind": "sfsp_led_cmd", "data_hex": data.hex().upper()})
        return out

    if can_id == ANALOG_ID:
        out.append({"kind": "panel_analog_unresolved", "data_hex": data.hex().upper()})
        return out

    return out


def format_event(frame: Frame, event: dict) -> str:
    prefix = f"{frame.timestamp:.6f} " if frame.timestamp is not None else ""
    kind = event["kind"]
    if kind == "switch":
        return f"{prefix}SWITCH {event['name']} {event['action'].upper()} key={event['key_hex']}"
    if kind == "output_state":
        return (
            f"{prefix}STATE output={event['output']:02d} {event['name']}="
            f"{'ON' if event['on'] else 'OFF'} can={event['state_can_id']}"
        )
    if kind == "digital_inputs":
        active = [name for name, value in event["signals"].items() if value]
        return f"{prefix}INPUT raw={event['raw_hex']} active={','.join(active) if active else 'none'}"
    if kind == "alive":
        return f"{prefix}ALIVE firmware={event['firmware']} config_crc={event['configuration_crc']}"
    return f"{prefix}{kind.upper()} {event.get('data_hex', '')}".rstrip()


def decode_log(path: Path, as_json: bool = False) -> int:
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        frame = parse_candump_line(line)
        if not frame:
            continue
        for event in decode_frame(frame):
            if as_json:
                record = {"line": line_number, "can_id": f"0x{frame.can_id:08X}", **event}
                if frame.timestamp is not None:
                    record["timestamp"] = frame.timestamp
                print(json.dumps(record, sort_keys=True))
            else:
                print(f"L{line_number:04d} {format_event(frame, event)}")
    return 0


def _require_python_can():
    try:
        import can  # type: ignore
    except ImportError as exc:
        raise SystemExit("python-can is required for live mode: pip install 'python-can>=4.3,<5'") from exc
    return can


def live_monitor(channel: str) -> int:
    can = _require_python_can()
    filters = [{"can_id": cid, "can_mask": 0x1FFFFFFF, "extended": True} for cid in
               [ALIVE_ID, DIGITAL_INPUT_ID, *STATE_IDS, SWITCH_ID, SYNC_ID, LED_CMD_ID]]
    with can.Bus(interface="socketcan", channel=channel, can_filters=filters) as bus:
        for msg in bus:
            frame = Frame(msg.timestamp, channel, msg.arbitration_id, bytes(msg.data))
            for event in decode_frame(frame):
                print(format_event(frame, event), flush=True)
    return 0


def build_key_frames(name: str) -> tuple[bytes, bytes]:
    if name not in NAME_TO_KEY:
        raise KeyError(name)
    key = NAME_TO_KEY[name]
    # Captured panel uses four-byte SwitchId 0x00000001 then the key byte.
    return b"\x00\x00\x00\x01" + bytes([key | 0x80]), b"\x00\x00\x00\x01" + bytes([key])


def press_key(channel: str, name: str, duration: float, transmit: bool) -> int:
    press, release = build_key_frames(name)
    print(f"press:   cansend {channel} {SWITCH_ID:08X}#{press.hex().upper()}")
    print(f"release: cansend {channel} {SWITCH_ID:08X}#{release.hex().upper()}")
    if not transmit:
        print("dry-run only; add --transmit to place frames on the bus", file=sys.stderr)
        return 0
    can = _require_python_can()
    with can.Bus(interface="socketcan", channel=channel) as bus:
        bus.send(can.Message(arbitration_id=SWITCH_ID, is_extended_id=True, data=press))
        time.sleep(duration)
        bus.send(can.Message(arbitration_id=SWITCH_ID, is_extended_id=True, data=release))
    return 0


def query_states(channel: str, transmit: bool) -> int:
    for can_id in STATE_IDS:
        print(f"RTR: cansend {channel} {can_id:08X}#R8")
    if not transmit:
        print("dry-run only; add --transmit to send RTR state requests", file=sys.stderr)
        return 0
    can = _require_python_can()
    with can.Bus(interface="socketcan", channel=channel) as bus:
        for can_id in STATE_IDS:
            bus.send(can.Message(arbitration_id=can_id, is_extended_id=True,
                                 is_remote_frame=True, dlc=8))
            time.sleep(0.03)
    return 0


def main(argv: Optional[Iterable[str]] = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    mode = p.add_mutually_exclusive_group(required=True)
    mode.add_argument("--log", type=Path, help="decode candump -L logfile")
    mode.add_argument("--monitor", action="store_true", help="live decode selected panel frames")
    mode.add_argument("--press", choices=sorted(NAME_TO_KEY), help="emit one captured-style button press/release")
    mode.add_argument("--query-states", action="store_true", help="send state RTR requests for output pairs 1..12")
    p.add_argument("--channel", default="can1")
    p.add_argument("--duration", type=float, default=0.150, help="button hold time in seconds (default 0.150)")
    p.add_argument("--transmit", action="store_true", help="required for active CAN transmission")
    p.add_argument("--json", action="store_true", help="JSON-lines output for --log")
    args = p.parse_args(list(argv) if argv is not None else None)

    if args.log:
        return decode_log(args.log, args.json)
    if args.monitor:
        return live_monitor(args.channel)
    if args.press:
        return press_key(args.channel, args.press, args.duration, args.transmit)
    if args.query_states:
        return query_states(args.channel, args.transmit)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
