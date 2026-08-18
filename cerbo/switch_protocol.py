#!/usr/bin/env python3
"""Pure Scheiber V8 control-panel protocol/state model for Cerbo integration.

This module intentionally contains no D-Bus, GLib or SocketCAN runtime code so
its state/transition logic can be regression-tested off-device.

Evidence basis: docs/control-panel-v8 from PR #7 / commit
8da4e30da12e95559cfb3562a7775800f70a6616.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Dict, Iterable, List, Optional, Tuple

ALIVE_ID = 0x00001808
DIGITAL_INPUT_ID = 0x02141808
STATE_IDS = (
    0x02161808,
    0x02181808,
    0x021A1808,
    0x021C1808,
    0x021E1808,
    0x02201808,
)
SWITCH_ID = 0x04001808
SWITCH_DEVICE_ID = 0x00000001
PANEL_PRESS_SECONDS = 0.150

# Victron gui-v2 SwitchableOutput types/statuses used by the bridge.
VICTRON_TYPE_TOGGLE = 1
VICTRON_TYPE_THREE_STATE = 9
VICTRON_STATUS_OFF = 0x00
VICTRON_STATUS_ON = 0x09
VICTRON_STATUS_OUTPUT_FAULT = 0x08

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

KEYS = {
    "electronics": 0x02,
    "navigation_lights": 0x03,
    "steaming_light": 0x04,
    "deck_floodlight": 0x05,
    "anchor_light": 0x06,
    "lighting": 0x07,
    "bilge_port_auto": 0x08,
    "bilge_starboard_auto": 0x09,
    "fresh_water_pump": 0x0A,
    "fridge_unit": 0x0B,
    "bilge_port_manual": 0x0C,
    "bilge_starboard_manual": 0x0D,
}

DIGITAL_INPUT_BITS = {
    "fresh_water_pump": 0,
    "bilge_port": 1,
    "bilge_starboard": 2,
}


@dataclass(frozen=True)
class ChannelSpec:
    channel_id: str
    name: str
    group: str
    ui_type: int
    output: Optional[int] = None
    key_name: Optional[str] = None
    auto_output: Optional[int] = None
    manual_output: Optional[int] = None
    auto_key_name: Optional[str] = None
    manual_key_name: Optional[str] = None
    running_signal: Optional[str] = None
    supports_automation: bool = False


CHANNELS: Tuple[ChannelSpec, ...] = (
    ChannelSpec("electronics", "Electronics", "Navigation", VICTRON_TYPE_TOGGLE,
                output=1, key_name="electronics"),
    ChannelSpec("deck_floodlight", "Deck Floodlight", "Lighting", VICTRON_TYPE_TOGGLE,
                output=2, key_name="deck_floodlight"),
    ChannelSpec("navigation_lights", "Navigation Lights", "Navigation", VICTRON_TYPE_TOGGLE,
                output=3, key_name="navigation_lights"),
    ChannelSpec("anchor_light", "Anchor Light", "Navigation", VICTRON_TYPE_THREE_STATE,
                output=4, key_name="anchor_light", supports_automation=True),
    ChannelSpec("steaming_light", "Steaming Light", "Navigation", VICTRON_TYPE_TOGGLE,
                output=5, key_name="steaming_light"),
    ChannelSpec("bilge_port", "Port Bilge Pump", "Pumps", VICTRON_TYPE_THREE_STATE,
                auto_output=6, manual_output=7, auto_key_name="bilge_port_auto",
                manual_key_name="bilge_port_manual", running_signal="bilge_port"),
    ChannelSpec("bilge_starboard", "Starboard Bilge Pump", "Pumps", VICTRON_TYPE_THREE_STATE,
                auto_output=8, manual_output=9, auto_key_name="bilge_starboard_auto",
                manual_key_name="bilge_starboard_manual", running_signal="bilge_starboard"),
    ChannelSpec("fresh_water_pump", "Fresh Water Pump", "Pumps", VICTRON_TYPE_THREE_STATE,
                output=10, key_name="fresh_water_pump", running_signal="fresh_water_pump",
                supports_automation=True),
    ChannelSpec("fridge_unit", "Fridge Unit", "House", VICTRON_TYPE_TOGGLE,
                output=11, key_name="fridge_unit"),
    ChannelSpec("lighting", "General Lighting", "Lighting", VICTRON_TYPE_TOGGLE,
                output=12, key_name="lighting"),
)
CHANNEL_BY_ID = {c.channel_id: c for c in CHANNELS}


class BilgeMode(str, Enum):
    UNKNOWN = "UNKNOWN"
    OFF = "OFF"
    AUTO = "AUTO"
    MANUAL = "MANUAL"
    INVALID = "INVALID"


@dataclass(frozen=True)
class KeyAction:
    """One panel-style key action; multiple key names means a chord."""
    keys: Tuple[str, ...]
    expected_bilge_mode: Optional[BilgeMode] = None
    expected_output: Optional[Tuple[int, bool]] = None
    description: str = ""


def build_key_frames(key_name: str) -> Tuple[bytes, bytes]:
    key = KEYS[key_name]
    prefix = SWITCH_DEVICE_ID.to_bytes(4, "big")
    return prefix + bytes([key | 0x80]), prefix + bytes([key])


def output_for_state_id(can_id: int, slot: int) -> int:
    group = STATE_IDS.index(can_id)
    return group * 2 + slot


def decode_output_state(can_id: int, data: bytes) -> Dict[int, bool]:
    if can_id not in STATE_IDS or len(data) < 8:
        return {}
    return {
        output_for_state_id(can_id, 1): bool(data[2] & 0x01),
        output_for_state_id(can_id, 2): bool(data[6] & 0x01),
    }


def decode_running_inputs(data: bytes) -> Dict[str, bool]:
    if not data:
        return {}
    value = data[0]
    return {name: bool(value & (1 << bit)) for name, bit in DIGITAL_INPUT_BITS.items()}


def derive_bilge_mode(auto_state: Optional[bool], manual_state: Optional[bool]) -> BilgeMode:
    if auto_state is None or manual_state is None:
        return BilgeMode.UNKNOWN
    if not auto_state and not manual_state:
        return BilgeMode.OFF
    if auto_state and not manual_state:
        return BilgeMode.AUTO
    if auto_state and manual_state:
        return BilgeMode.MANUAL
    # AUTO=0/MANUAL=1 was not established in the captures and must not be
    # treated as a valid state.
    return BilgeMode.INVALID


def bilge_ui_values(mode: BilgeMode) -> Tuple[Optional[int], Optional[int]]:
    """Return native type-9 (/State, /Auto) representation.

    OFF    -> State=0 Auto=0
    AUTO   -> State=0 Auto=1
    MANUAL -> State=1 Auto=0
    """
    return {
        BilgeMode.OFF: (0, 0),
        BilgeMode.AUTO: (0, 1),
        BilgeMode.MANUAL: (1, 0),
        BilgeMode.UNKNOWN: (None, None),
        BilgeMode.INVALID: (None, None),
    }[mode]


def bilge_mode_from_ui(state: int, auto: int) -> BilgeMode:
    state = int(state)
    auto = int(auto)
    if auto:
        return BilgeMode.AUTO
    return BilgeMode.MANUAL if state else BilgeMode.OFF


def plan_binary_transition(spec: ChannelSpec, actual: Optional[bool], desired: bool) -> List[KeyAction]:
    if spec.output is None or spec.key_name is None:
        raise ValueError("channel is not a binary Scheiber output")
    if actual is None:
        raise ValueError("actual state is UNKNOWN")
    desired = bool(desired)
    if actual == desired:
        return []
    return [KeyAction(
        keys=(spec.key_name,),
        expected_output=(spec.output, desired),
        description="{} -> {}".format(spec.name, "ON" if desired else "OFF"),
    )]


def plan_bilge_transition(spec: ChannelSpec, current: BilgeMode, desired: BilgeMode) -> List[KeyAction]:
    if spec.auto_key_name is None or spec.manual_key_name is None:
        raise ValueError("channel is not a bilge channel")
    if current in (BilgeMode.UNKNOWN, BilgeMode.INVALID):
        raise ValueError("current bilge mode is {}".format(current.value))
    if desired not in (BilgeMode.OFF, BilgeMode.AUTO, BilgeMode.MANUAL):
        raise ValueError("invalid desired bilge mode")
    if current == desired:
        return []

    auto_key = spec.auto_key_name
    manual_key = spec.manual_key_name

    # These paths mirror the labelled capture. MANUAL->OFF used a simultaneous
    # AUTO+MANUAL press. OFF->MANUAL deliberately passes through AUTO so the
    # unobserved AUTO=0/MANUAL=1 combination is never created.
    table = {
        (BilgeMode.OFF, BilgeMode.AUTO): [
            KeyAction((auto_key,), BilgeMode.AUTO, description="OFF -> AUTO")
        ],
        (BilgeMode.AUTO, BilgeMode.OFF): [
            KeyAction((auto_key,), BilgeMode.OFF, description="AUTO -> OFF")
        ],
        (BilgeMode.AUTO, BilgeMode.MANUAL): [
            KeyAction((manual_key,), BilgeMode.MANUAL, description="AUTO -> MANUAL")
        ],
        (BilgeMode.MANUAL, BilgeMode.AUTO): [
            KeyAction((manual_key,), BilgeMode.AUTO, description="MANUAL -> AUTO")
        ],
        (BilgeMode.MANUAL, BilgeMode.OFF): [
            KeyAction((auto_key, manual_key), BilgeMode.OFF,
                      description="MANUAL -> OFF (observed two-key chord)")
        ],
        (BilgeMode.OFF, BilgeMode.MANUAL): [
            KeyAction((auto_key,), BilgeMode.AUTO, description="OFF -> AUTO (safe intermediate)"),
            KeyAction((manual_key,), BilgeMode.MANUAL, description="AUTO -> MANUAL"),
        ],
    }
    return table[(current, desired)]


class SwitchStateModel:
    def __init__(self) -> None:
        self.outputs: Dict[int, Optional[bool]] = {n: None for n in OUTPUT_NAMES}
        self.running: Dict[str, Optional[bool]] = {
            "fresh_water_pump": None,
            "bilge_port": None,
            "bilge_starboard": None,
        }
        self.panel_alive_seen = False

    def update_frame(self, can_id: int, data: bytes) -> bool:
        """Apply a decoded frame; return True when model-visible state changed."""
        changed = False
        if can_id == ALIVE_ID:
            if not self.panel_alive_seen:
                self.panel_alive_seen = True
                changed = True
            return changed
        if can_id in STATE_IDS:
            for output, state in decode_output_state(can_id, data).items():
                if self.outputs[output] is None or self.outputs[output] != state:
                    self.outputs[output] = state
                    changed = True
            return changed
        if can_id == DIGITAL_INPUT_ID:
            for name, state in decode_running_inputs(data).items():
                if self.running[name] is None or self.running[name] != state:
                    self.running[name] = state
                    changed = True
            return changed
        return False

    def output(self, number: int) -> Optional[bool]:
        return self.outputs[number]

    def channel_binary_state(self, channel_id: str) -> Optional[bool]:
        spec = CHANNEL_BY_ID[channel_id]
        if spec.output is None:
            return None
        return self.output(spec.output)

    def bilge_mode(self, channel_id: str) -> BilgeMode:
        spec = CHANNEL_BY_ID[channel_id]
        if spec.auto_output is None or spec.manual_output is None:
            raise ValueError("not a bilge channel")
        return derive_bilge_mode(self.output(spec.auto_output), self.output(spec.manual_output))

    def running_state(self, channel_id: str) -> Optional[bool]:
        spec = CHANNEL_BY_ID[channel_id]
        if spec.running_signal is None:
            return None
        return self.running[spec.running_signal]

    def channel_synchronized(self, channel_id: str) -> bool:
        spec = CHANNEL_BY_ID[channel_id]
        if spec.output is not None:
            return self.output(spec.output) is not None
        return (
            spec.auto_output is not None
            and spec.manual_output is not None
            and self.output(spec.auto_output) is not None
            and self.output(spec.manual_output) is not None
        )

    def all_outputs_synchronized(self) -> bool:
        return all(v is not None for v in self.outputs.values())


def relevant_can_ids() -> Iterable[int]:
    return (ALIVE_ID, DIGITAL_INPUT_ID, *STATE_IDS, SWITCH_ID)
