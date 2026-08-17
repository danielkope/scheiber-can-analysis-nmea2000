"""Core data types and candump parsing for the Scheiber CAN analyzer."""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

CANDUMP_RE = re.compile(
    r"^\((?P<timestamp>\d+(?:\.\d+)?)\)\s+"
    r"(?P<interface>\S+)\s+"
    r"(?P<can_id>[0-9A-Fa-f]+)#(?P<data>[0-9A-Fa-f]*)$"
)

SELECTOR_ENUM = {0x01: "OFF", 0x02: "SHORE", 0x04: "GENERATOR"}
GENERATOR_COMMAND_ENUM = {0x01: "START", 0x02: "STOP"}
GENERATOR_STATUS_ENUM = {
    0x00: "OFF_IDLE",
    0x01: "RUNNING_SETTLED",
    0x02: "STARTING",
    0x03: "STARTING",
    0x04: "STOPPING",
    0x05: "STOPPING",
}
HOUSE_BATTERY_IDS = {
    0x06020580: "house_battery_candidate_1",
    0x06060580: "house_battery_candidate_2",
    0x060A0580: "house_battery_candidate_3",
    0x060E0580: "house_battery_candidate_4",
    0x06120580: "house_battery_candidate_5",
    0x06160580: "house_battery_candidate_6",
}
CHARGER_SUFFIXES = {0x1008: "charger_candidate_1008", 0x1010: "charger_candidate_1010", 0x1020: "charger_candidate_1020"}
CHARGER_RATING_GUESSES = {0x1008: 60, 0x1010: 40, 0x1020: 25}


@dataclass(frozen=True)
class CandumpFrame:
    line_number: int
    timestamp: float
    interface: str
    can_id: int
    data: bytes

    @property
    def can_id_hex(self) -> str:
        return f"{self.can_id:08X}"

    @property
    def data_hex(self) -> str:
        return self.data.hex().upper()

    @property
    def dlc(self) -> int:
        return len(self.data)


@dataclass
class DecodedRecord:
    line_number: int
    timestamp: float
    relative_seconds: float
    interface: str
    can_id: str
    data_hex: str
    category: str
    name: str
    value: Any
    unit: str
    datatype: str
    endian: str
    scale: str
    offset: str
    confidence: str
    status: str
    notes: str


def u16be(data: bytes, offset: int) -> int:
    return int.from_bytes(data[offset : offset + 2], "big", signed=False)


def u16le(data: bytes, offset: int) -> int:
    return int.from_bytes(data[offset : offset + 2], "little", signed=False)


def parse_candump(path: Path) -> list[CandumpFrame]:
    frames: list[CandumpFrame] = []
    with path.open("r", encoding="utf-8", errors="strict") as handle:
        for line_number, line in enumerate(handle, start=1):
            stripped = line.strip()
            if not stripped:
                continue
            match = CANDUMP_RE.match(stripped)
            if not match:
                raise ValueError(f"Unrecognized candump syntax at line {line_number}: {stripped!r}")
            data_hex = match.group("data")
            if len(data_hex) % 2:
                raise ValueError(f"Odd number of data hex characters at line {line_number}")
            frames.append(
                CandumpFrame(
                    line_number=line_number,
                    timestamp=float(match.group("timestamp")),
                    interface=match.group("interface"),
                    can_id=int(match.group("can_id"), 16),
                    data=bytes.fromhex(data_hex),
                )
            )
    if not frames:
        raise ValueError(f"No frames found in {path}")
    return frames


def record(
    frame: CandumpFrame,
    start_ts: float,
    *,
    category: str,
    name: str,
    value: Any,
    unit: str = "",
    datatype: str = "",
    endian: str = "",
    scale: str = "1",
    offset: str = "0",
    confidence: str = "",
    status: str = "",
    notes: str = "",
) -> DecodedRecord:
    return DecodedRecord(
        line_number=frame.line_number,
        timestamp=frame.timestamp,
        relative_seconds=round(frame.timestamp - start_ts, 6),
        interface=frame.interface,
        can_id=frame.can_id_hex,
        data_hex=frame.data_hex,
        category=category,
        name=name,
        value=value,
        unit=unit,
        datatype=datatype,
        endian=endian,
        scale=scale,
        offset=offset,
        confidence=confidence,
        status=status,
        notes=notes,
    )
