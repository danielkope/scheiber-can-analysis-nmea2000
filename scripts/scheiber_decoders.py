"""Conservative field decoders for observed Scheiber CAN frames."""
from __future__ import annotations

from pathlib import Path
import sys
from typing import Mapping

_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

from scheiber_can_core import (  # noqa: E402
    CHARGER_RATING_GUESSES,
    CHARGER_SUFFIXES,
    GENERATOR_COMMAND_ENUM,
    HOUSE_BATTERY_IDS,
    SELECTOR_ENUM,
    CandumpFrame,
    DecodedRecord,
    record,
    u16be,
    u16le,
)

def decode_frame(frame: CandumpFrame, start_ts: float, capacities: Mapping[str, float]) -> list[DecodedRecord]:
    out: list[DecodedRecord] = []
    cid = frame.can_id
    data = frame.data

    if cid == 0x02040580 and len(data) == 8:
        levels = [u16be(data, 0), u16be(data, 2), u16be(data, 4)]
        tanks = [
            ("water", levels[0], capacities["water_l"]),
            ("diesel_1", levels[1], capacities["diesel_1_l"]),
            ("diesel_2", levels[2], capacities["diesel_2_l"]),
        ]
        for tank_name, pct, capacity in tanks:
            out.append(record(frame, start_ts, category="tank", name=f"{tank_name}_level", value=pct,
                              unit="%", datatype="uint16", endian="big", confidence="high", status="confirmed",
                              notes=f"Litres = percentage * {capacity:g} L / 100"))
            out.append(record(frame, start_ts, category="tank", name=f"{tank_name}_volume", value=round(pct * capacity / 100.0, 1),
                              unit="L", datatype="derived float", endian="n/a", scale=f"capacity={capacity:g} L",
                              confidence="high", status="derived", notes="Derived from user-supplied tank capacity."))
        out.append(record(frame, start_ts, category="tank", name="tank_frame_state_raw", value=u16be(data, 6),
                          datatype="uint16", endian="big", confidence="low", status="unresolved",
                          notes="Observed 0, 1 and 2; possibly quality, sample phase, or sequence."))
        return out

    panel_map = {
        0x02420B90: ("ac_panel", "requested_source"),
        0x02400B90: ("ac_panel", "applied_source"),
        0x02420B88: ("house_panel", "requested_source"),
        0x02400B88: ("house_panel", "applied_source"),
    }
    if cid in panel_map and len(data) == 1:
        panel, field = panel_map[cid]
        raw = data[0]
        out.append(record(frame, start_ts, category="panel", name=f"{panel}_{field}", value=SELECTOR_ENUM.get(raw, f"UNKNOWN_0x{raw:02X}"),
                          unit="enum", datatype="uint8 enum", confidence="high", status="confirmed",
                          notes="Enum established by the operator's ordered OFF/shore/generator actions."))
        out.append(record(frame, start_ts, category="panel", name=f"{panel}_{field}_raw", value=raw,
                          unit="raw", datatype="uint8", confidence="high", status="confirmed"))
        return out

    if cid == 0x02460B88 and len(data) == 1:
        raw = data[0]
        out.append(record(frame, start_ts, category="generator", name="generator_command",
                          value=GENERATOR_COMMAND_ENUM.get(raw, f"UNKNOWN_0x{raw:02X}"),
                          unit="enum", datatype="uint8 enum", confidence="high", status="confirmed",
                          notes="0x01=START and 0x02=STOP confirmed by the operator. Semantic mapping is confirmed; replay safety, acknowledgements, timing, and interlocks remain unvalidated."))
        out.append(record(frame, start_ts, category="generator", name="generator_command_raw", value=raw,
                          unit="raw", datatype="uint8", confidence="high", status="confirmed",
                          notes="Direct generator command byte on CAN ID 0x02460B88."))
        return out

    if cid == 0x02040898 and len(data) == 4:
        out.append(record(frame, start_ts, category="ac", name="generator_or_ac_module_voltage", value=u16be(data, 0),
                          unit="V", datatype="uint16", endian="big", confidence="high", status="confirmed",
                          notes="Clean 0-to-230/235 V ramps; device role is generator/AC module candidate."))
        out.append(record(frame, start_ts, category="ac", name="generator_or_ac_module_frequency", value=u16be(data, 2),
                          unit="Hz", datatype="uint16", endian="big", confidence="high", status="confirmed",
                          notes="Observed 50 Hz when energized and 0 Hz while de-energized."))
        return out

    if cid in (0x02040B88, 0x02040B90) and len(data) == 8:
        panel = "house_panel" if cid == 0x02040B88 else "ac_panel"
        out.append(record(frame, start_ts, category="ac", name=f"{panel}_voltage", value=u16be(data, 4),
                          unit="V", datatype="uint16", endian="big", confidence="high", status="confirmed",
                          notes="Bytes 0-3 are zero in this capture; bytes 4-5 track AC voltage."))
        out.append(record(frame, start_ts, category="ac", name=f"{panel}_frequency_or_status_raw", value=u16be(data, 6),
                          unit="raw (usually Hz)", datatype="uint16", endian="big", confidence="medium", status="candidate",
                          notes="Usually 50 while energized and 0 while off; a few transition values imply status bits or a transient encoding."))
        return out

    if cid == 0x02060B88 and len(data) == 4:
        raw = u16be(data, 0)
        out.append(record(frame, start_ts, category="dc", name="house_panel_dc_voltage_candidate", value=round(raw / 10.0, 1),
                          unit="V", datatype="uint16", endian="big", scale="0.1", confidence="medium-high", status="candidate",
                          notes="Raw range 102-140 is physically plausible as 10.2-14.0 V; second word is 0x7FFF unavailable."))
        return out

    if cid == 0x02140898 and len(data) == 1:
        marker = {0x02: "AC_RAMP_DOWN_MARKER", 0x03: "AC_RAMP_UP_MARKER"}.get(data[0], f"UNKNOWN_0x{data[0]:02X}")
        out.append(record(frame, start_ts, category="generator", name="generator_or_ac_transition_marker", value=marker,
                          unit="enum candidate", datatype="uint8 enum", confidence="medium", status="candidate",
                          notes="0x02 precedes clean voltage ramp-down; 0x03 precedes clean ramp-up. These are transition markers distinct from the confirmed direct commands on 0x02460B88."))
        return out

    if cid in HOUSE_BATTERY_IDS and len(data) == 6:
        node = HOUSE_BATTERY_IDS[cid]
        voltage_raw = u16le(data, 0)
        field2_raw = u16le(data, 2)
        current_code = field2_raw - 0x4E00
        field3 = u16le(data, 4)
        out.append(record(frame, start_ts, category="house_battery", name=f"{node}_voltage", value=round(voltage_raw / 100.0, 2),
                          unit="V", datatype="uint16", endian="little", scale="0.01", confidence="high", status="confirmed",
                          notes="Six parallel IDs have coherent 13.32-13.36 V values."))
        out.append(record(frame, start_ts, category="house_battery", name=f"{node}_current_code", value=current_code,
                          unit="code", datatype="offset uint16", endian="little", scale="unknown; 0.1 A/code is a working guess",
                          offset="-0x4E00", confidence="medium", status="candidate",
                          notes="Signed behavior is exact around the 0x4E00 zero point; physical amperes need a controlled load test."))
        out.append(record(frame, start_ts, category="house_battery", name=f"{node}_current_guess", value=round(current_code / 10.0, 1),
                          unit="A (guess)", datatype="derived float", endian="n/a", scale="0.1", offset="-0x4E00",
                          confidence="low-medium", status="guess", notes="Convenience hypothesis only; not yet calibration-grade."))
        out.append(record(frame, start_ts, category="house_battery", name=f"{node}_field3_raw", value=field3,
                          unit="% SoC guess or degF alternative", datatype="uint16", endian="little", confidence="low-medium", status="guess",
                          notes="Observed stable 72-74. Packet structure favors SoC; temperature in degF remains a credible alternative."))
        return out

    # Three repeated charger device families use suffix 0x1008/0x1010/0x1020.
    suffix = cid & 0xFFFF
    if suffix in CHARGER_SUFFIXES and len(data) == 8:
        prefix = cid >> 16
        node = CHARGER_SUFFIXES[suffix]
        if prefix == 0x0050:
            words = [u16le(data, i) for i in (0, 2, 4, 6)]
            names = ["dc_output_voltage_candidate", "dc_output_current_candidate", "ac_input_voltage_candidate", "reserved_or_na"]
            units = ["V", "A", "V", "raw"]
            scales = ["0.1", "0.1", "0.1", "1"]
            confidences = ["medium-high", "medium", "high", "high"]
            statuses = ["candidate", "candidate", "candidate", "confirmed"]
            values: list[object] = [round(words[0] / 10.0, 1), round(words[1] / 10.0, 1), round(words[2] / 10.0, 1), words[3]]
            notes = [
                "13.x values while energized; some devices decay when isolated, consistent with charger output voltage.",
                "Dynamic values are physically plausible as 0.1 A but require independent ammeter validation.",
                "2290-2400 decodes cleanly as 229-240 V and becomes zero when AC is absent.",
                "0xFFFF throughout this capture, consistent with unavailable/reserved.",
            ]
            for n, val, unit, scale, conf, stat, note in zip(names, values, units, scales, confidences, statuses, notes):
                out.append(record(frame, start_ts, category="charger", name=f"{node}_{n}", value=val, unit=unit,
                                  datatype="uint16", endian="little", scale=scale, confidence=conf, status=stat, notes=note))
            return out
        if prefix == 0x0052:
            words = [u16le(data, i) for i in (0, 2, 4, 6)]
            out.append(record(frame, start_ts, category="charger", name=f"{node}_temperature_or_counter_raw", value=words[1],
                              unit="raw", datatype="uint16", endian="little", confidence="low", status="unresolved",
                              notes="Values 304-333 rise monotonically while active. Kelvin temperature is plausible but the linearity also fits a counter."))
            return out
        if prefix == 0x0054:
            out.append(record(frame, start_ts, category="charger", name=f"{node}_configuration_payload", value=frame.data_hex,
                              unit="hex", datatype="byte array", endian="mixed/unknown", confidence="low", status="unresolved",
                              notes="Sparse configuration/status message; 0x63 (99) and 0x0064 (100) recur, but field meanings are unvalidated."))
            return out
        if prefix == 0x0056:
            w0, w1 = u16le(data, 0), u16le(data, 2)
            nominal_v, rating_a, byte6, byte7 = data[4], data[5], data[6], data[7]
            out.append(record(frame, start_ts, category="charger", name=f"{node}_channel_a_raw_scaled", value=round(w0 / 10.0, 1),
                              unit="V/A candidate", datatype="uint16", endian="little", scale="0.1", confidence="low-medium", status="candidate",
                              notes="First dynamic channel; often near 13.x. Exact voltage/current role varies by node and needs bench correlation."))
            out.append(record(frame, start_ts, category="charger", name=f"{node}_channel_b_raw_scaled", value=round(w1 / 10.0, 1),
                              unit="V/A candidate", datatype="uint16", endian="little", scale="0.1", confidence="low-medium", status="candidate",
                              notes="Second dynamic channel; may represent a second output, setpoint, or current."))
            out.append(record(frame, start_ts, category="charger", name=f"{node}_nominal_voltage_signature", value=nominal_v,
                              unit="V candidate", datatype="uint8", confidence="medium-high", status="candidate",
                              notes="Constant 12 on all three device families."))
            out.append(record(frame, start_ts, category="charger", name=f"{node}_rated_current_signature", value=rating_a,
                              unit="A candidate", datatype="uint8", confidence="medium-high", status="candidate",
                              notes=f"Constant {rating_a}; matches the credible 12 V/{CHARGER_RATING_GUESSES[suffix]} A charger-rating interpretation."))
            out.append(record(frame, start_ts, category="charger", name=f"{node}_config_byte6", value=byte6,
                              unit="raw", datatype="uint8", confidence="low", status="unresolved"))
            out.append(record(frame, start_ts, category="charger", name=f"{node}_config_byte7", value=byte7,
                              unit="raw", datatype="uint8", confidence="low", status="unresolved"))
            return out
        if prefix == 0x005A:
            raw = u16le(data, 0)
            out.append(record(frame, start_ts, category="charger", name=f"{node}_ac_frequency", value=round(raw / 10.0, 1),
                              unit="Hz", datatype="uint16", endian="little", scale="0.1", confidence="high", status="candidate",
                              notes="500 = 50.0 Hz, 400 = 40.0 Hz during decay, 0 = off; remaining words are 0xFFFF."))
            return out

    return out


