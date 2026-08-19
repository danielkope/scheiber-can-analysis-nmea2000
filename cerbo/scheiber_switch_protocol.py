#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Pure protocol/state layer for the Scheiber V8 native GX switch service.

The physical panel emits momentary key events. They are not explicit ON/OFF
commands, so the controller must learn actual output state first and only press
a key when known actual state differs from the requested state.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Iterable, List, Mapping, Optional, Tuple

PANEL_ALIVE_ID = 0x00001808
DIGITAL_INPUT_ID = 0x02141808
STATE_IDS: Tuple[int, ...] = (
    0x02161808,
    0x02181808,
    0x021A1808,
    0x021C1808,
    0x021E1808,
    0x02201808,
)
SWITCH_EVENT_ID = 0x04001808

MODE_OFF = "OFF"
MODE_AUTO = "AUTO"
MODE_MANUAL = "MANUAL"
MODE_UNKNOWN = "UNKNOWN"
MODE_INVALID = "INVALID"
VALID_BILGE_MODES = (MODE_OFF, MODE_AUTO, MODE_MANUAL)

KIND_BINARY = "binary"
KIND_BILGE = "bilge"
UI_TYPE_TOGGLE = 1
UI_TYPE_THREE_STATE = 9


@dataclass(frozen=True)
class PhysicalOutput:
    number: int
    name: str
    key_code: int
    state_can_id: int
    state_slot: int


PHYSICAL_OUTPUTS: Tuple[PhysicalOutput, ...] = (
    PhysicalOutput(1, "electronics", 0x02, 0x02161808, 1),
    PhysicalOutput(2, "deck_floodlight", 0x05, 0x02161808, 2),
    PhysicalOutput(3, "navigation_lights", 0x03, 0x02181808, 1),
    PhysicalOutput(4, "anchor_light", 0x06, 0x02181808, 2),
    PhysicalOutput(5, "steaming_light", 0x04, 0x021A1808, 1),
    PhysicalOutput(6, "bilge_port_auto", 0x08, 0x021A1808, 2),
    PhysicalOutput(7, "bilge_port_manual", 0x0C, 0x021C1808, 1),
    PhysicalOutput(8, "bilge_starboard_auto", 0x09, 0x021C1808, 2),
    PhysicalOutput(9, "bilge_starboard_manual", 0x0D, 0x021E1808, 1),
    PhysicalOutput(10, "fresh_water_pump_enabled", 0x0A, 0x021E1808, 2),
    PhysicalOutput(11, "fridge_unit", 0x0B, 0x02201808, 1),
    PhysicalOutput(12, "lighting", 0x07, 0x02201808, 2),
)
OUTPUT_BY_NUMBER: Mapping[int, PhysicalOutput] = {
    output.number: output for output in PHYSICAL_OUTPUTS
}
STATE_FRAME_OUTPUTS: Mapping[int, Tuple[int, int]] = {
    can_id: (index * 2 + 1, index * 2 + 2)
    for index, can_id in enumerate(STATE_IDS)
}

RUNNING_BITS: Mapping[str, int] = {
    "fresh_water_pump_running": 0,
    "bilge_port_running": 1,
    "bilge_starboard_running": 2,
}


@dataclass(frozen=True)
class Channel:
    channel_id: str
    display_name: str
    group: str
    kind: str
    ui_type: int
    output: Optional[int] = None
    auto_output: Optional[int] = None
    manual_output: Optional[int] = None
    running_signal: Optional[str] = None
    persisted_auto: bool = False

    @property
    def physical_outputs(self) -> Tuple[int, ...]:
        if self.kind == KIND_BINARY and self.output is not None:
            return (self.output,)
        if self.kind == KIND_BILGE and self.auto_output is not None and self.manual_output is not None:
            return (self.auto_output, self.manual_output)
        raise ValueError(f"incomplete channel definition: {self.channel_id}")


CHANNELS: Tuple[Channel, ...] = (
    Channel("electronics", "Electronics", "Systems", KIND_BINARY, UI_TYPE_TOGGLE, output=1),
    Channel("deck_floodlight", "Deck Floodlight", "Lighting", KIND_BINARY, UI_TYPE_TOGGLE, output=2),
    Channel("navigation_lights", "Navigation Lights", "Navigation", KIND_BINARY, UI_TYPE_TOGGLE, output=3),
    Channel("anchor_light", "Anchor Light", "Navigation", KIND_BINARY, UI_TYPE_THREE_STATE, output=4, persisted_auto=True),
    Channel("steaming_light", "Steaming Light", "Navigation", KIND_BINARY, UI_TYPE_TOGGLE, output=5),
    Channel("bilge_port", "Port Bilge Pump", "Pumps", KIND_BILGE, UI_TYPE_THREE_STATE,
            auto_output=6, manual_output=7, running_signal="bilge_port_running"),
    Channel("bilge_starboard", "Starboard Bilge Pump", "Pumps", KIND_BILGE, UI_TYPE_THREE_STATE,
            auto_output=8, manual_output=9, running_signal="bilge_starboard_running"),
    Channel("fresh_water_pump", "Fresh Water Pump", "Pumps", KIND_BINARY, UI_TYPE_TOGGLE,
            output=10, running_signal="fresh_water_pump_running"),
    Channel("fridge_unit", "Fridge Unit", "Systems", KIND_BINARY, UI_TYPE_TOGGLE, output=11),
    Channel("lighting", "General Lighting", "Lighting", KIND_BINARY, UI_TYPE_TOGGLE, output=12),
)
CHANNEL_BY_ID: Mapping[str, Channel] = {channel.channel_id: channel for channel in CHANNELS}


@dataclass(frozen=True)
class CommandStep:
    key_code: int
    key_name: str
    expected_outputs: Tuple[Tuple[int, bool], ...]
    description: str

    def satisfied(self, outputs: Mapping[int, Optional[bool]]) -> bool:
        return all(outputs.get(number) is expected for number, expected in self.expected_outputs)


class UnknownStateError(RuntimeError):
    pass


class InvalidStateError(RuntimeError):
    pass


def decode_output_state(can_id: int, data: bytes) -> Dict[int, bool]:
    """Decode one paired state frame; command bits are byte 2/6 bit 0."""
    if can_id not in STATE_FRAME_OUTPUTS:
        return {}
    if len(data) < 8:
        raise ValueError(f"state frame 0x{can_id:08X} must contain 8 bytes")
    first, second = STATE_FRAME_OUTPUTS[can_id]
    return {first: bool(data[2] & 0x01), second: bool(data[6] & 0x01)}


def decode_running(data: bytes) -> Dict[str, bool]:
    if not data:
        raise ValueError("digital-input frame must contain at least one byte")
    value = data[0]
    return {name: bool(value & (1 << bit)) for name, bit in RUNNING_BITS.items()}


def build_key_payloads(key_code: int, switch_device_id: int = 1) -> Tuple[bytes, bytes]:
    if not 0 <= int(key_code) <= 0x7F:
        raise ValueError("key code must be 0x00..0x7F")
    prefix = int(switch_device_id).to_bytes(4, "big", signed=False)
    key = int(key_code)
    return prefix + bytes((key | 0x80,)), prefix + bytes((key,))


def bilge_mode(auto_state: Optional[bool], manual_state: Optional[bool]) -> str:
    if auto_state is None or manual_state is None:
        return MODE_UNKNOWN
    if not auto_state and not manual_state:
        return MODE_OFF
    if auto_state and not manual_state:
        return MODE_AUTO
    if auto_state and manual_state:
        return MODE_MANUAL
    return MODE_INVALID


def bilge_target_bits(mode: str) -> Tuple[bool, bool]:
    targets = {MODE_OFF: (False, False), MODE_AUTO: (True, False), MODE_MANUAL: (True, True)}
    if mode not in targets:
        raise ValueError(f"unsupported bilge mode: {mode}")
    return targets[mode]


def bilge_mode_to_dbus(mode: str, running: bool = False) -> Tuple[int, int]:
    """Return native three-state values as (State, Auto).

    ``Auto`` represents the selected Scheiber AUTO mode. ``State`` is the
    physical pump-activity lamp: it is set while the pump is actually running,
    including during an automatic float-triggered cycle. MANUAL is therefore
    represented by State=1, Auto=0; AUTO while idle is State=0, Auto=1; and AUTO
    while pumping is State=1, Auto=1.
    """
    if mode == MODE_OFF:
        return int(bool(running)), 0
    if mode == MODE_AUTO:
        return int(bool(running)), 1
    if mode == MODE_MANUAL:
        return int(bool(running)), 0
    raise ValueError(f"cannot publish bilge mode {mode}")


def plan_binary(channel: Channel, current: Optional[bool], target: bool) -> List[CommandStep]:
    if channel.kind != KIND_BINARY or channel.output is None:
        raise ValueError(f"{channel.channel_id} is not binary")
    if current is None:
        raise UnknownStateError(f"{channel.channel_id} state is UNKNOWN")
    target = bool(target)
    if current is target:
        return []
    physical = OUTPUT_BY_NUMBER[channel.output]
    return [CommandStep(physical.key_code, physical.name, ((physical.number, target),),
                        f"{channel.channel_id} -> {'ON' if target else 'OFF'}")]


def _bilge_step(channel: Channel, bit: str, auto_state: bool, manual_state: bool) -> CommandStep:
    output_number = channel.auto_output if bit == "auto" else channel.manual_output
    if output_number is None:
        raise ValueError(f"incomplete bilge channel: {channel.channel_id}")
    physical = OUTPUT_BY_NUMBER[output_number]
    return CommandStep(
        physical.key_code,
        physical.name,
        ((int(channel.auto_output), auto_state), (int(channel.manual_output), manual_state)),
        f"{channel.channel_id}: toggle {bit} -> {bilge_mode(auto_state, manual_state)}",
    )


def plan_bilge(channel: Channel, current_auto: Optional[bool], current_manual: Optional[bool],
               target_mode: str) -> List[CommandStep]:
    if channel.kind != KIND_BILGE:
        raise ValueError(f"{channel.channel_id} is not a bilge")
    if target_mode not in VALID_BILGE_MODES:
        raise ValueError(f"unsupported target mode: {target_mode}")
    current_mode = bilge_mode(current_auto, current_manual)
    if current_mode == MODE_UNKNOWN:
        raise UnknownStateError(f"{channel.channel_id} mode is UNKNOWN")
    if current_mode == MODE_INVALID:
        raise InvalidStateError(f"{channel.channel_id} has invalid AUTO=0/MANUAL=1 state")
    if current_mode == target_mode:
        return []

    paths: Mapping[Tuple[str, str], Tuple[str, ...]] = {
        (MODE_OFF, MODE_AUTO): ("auto",),
        (MODE_OFF, MODE_MANUAL): ("auto", "manual"),
        (MODE_AUTO, MODE_OFF): ("auto",),
        (MODE_AUTO, MODE_MANUAL): ("manual",),
        (MODE_MANUAL, MODE_AUTO): ("manual",),
        (MODE_MANUAL, MODE_OFF): ("manual", "auto"),
    }
    auto_state = bool(current_auto)
    manual_state = bool(current_manual)
    steps: List[CommandStep] = []
    for operation in paths[(current_mode, target_mode)]:
        if operation == "auto":
            auto_state = not auto_state
        else:
            manual_state = not manual_state
        if bilge_mode(auto_state, manual_state) not in VALID_BILGE_MODES:
            raise AssertionError("planner created unsafe bilge intermediate state")
        steps.append(_bilge_step(channel, operation, auto_state, manual_state))
    if (auto_state, manual_state) != bilge_target_bits(target_mode):
        raise AssertionError("bilge plan did not reach target")
    return steps


class StateModel:
    def __init__(self) -> None:
        self.outputs: Dict[int, Optional[bool]] = {output.number: None for output in PHYSICAL_OUTPUTS}
        self.running: Dict[str, Optional[bool]] = {name: None for name in RUNNING_BITS}
        self.last_digital_raw: Optional[int] = None

    def reset_unknown(self) -> None:
        for number in self.outputs:
            self.outputs[number] = None
        for name in self.running:
            self.running[name] = None
        self.last_digital_raw = None

    def apply(self, can_id: int, data: bytes) -> Tuple[Tuple[int, ...], Tuple[str, ...]]:
        changed_outputs: List[int] = []
        changed_running: List[str] = []
        if can_id in STATE_FRAME_OUTPUTS:
            for number, value in decode_output_state(can_id, data).items():
                if self.outputs[number] is not value:
                    self.outputs[number] = value
                    changed_outputs.append(number)
        elif can_id == DIGITAL_INPUT_ID:
            decoded = decode_running(data)
            self.last_digital_raw = data[0]
            for name, value in decoded.items():
                if self.running[name] is not value:
                    self.running[name] = value
                    changed_running.append(name)
        return tuple(changed_outputs), tuple(changed_running)

    def channel_known(self, channel: Channel) -> bool:
        return all(self.outputs[number] is not None for number in channel.physical_outputs)

    def binary_state(self, channel: Channel) -> Optional[bool]:
        if channel.kind != KIND_BINARY or channel.output is None:
            raise ValueError(f"{channel.channel_id} is not binary")
        return self.outputs[channel.output]

    def bilge_mode(self, channel: Channel) -> str:
        if channel.kind != KIND_BILGE:
            raise ValueError(f"{channel.channel_id} is not a bilge")
        return bilge_mode(self.outputs[int(channel.auto_output)], self.outputs[int(channel.manual_output)])

    def running_state(self, channel: Channel) -> Optional[bool]:
        return None if channel.running_signal is None else self.running[channel.running_signal]

    def missing_state_ids(self) -> Tuple[int, ...]:
        return tuple(can_id for can_id, outputs in STATE_FRAME_OUTPUTS.items()
                     if any(self.outputs[number] is None for number in outputs))

    def synchronized_outputs(self) -> Tuple[int, ...]:
        return tuple(number for number, value in self.outputs.items() if value is not None)

    def snapshot(self) -> Dict[str, object]:
        channels: Dict[str, object] = {}
        for channel in CHANNELS:
            control: object = self.binary_state(channel) if channel.kind == KIND_BINARY else self.bilge_mode(channel)
            channels[channel.channel_id] = {
                "control": control,
                "known": self.channel_known(channel),
                "running": self.running_state(channel),
            }
        return {
            "outputs": dict(self.outputs),
            "running": dict(self.running),
            "last_digital_raw": self.last_digital_raw,
            "channels": channels,
        }


def outputs_for_state_ids(state_ids: Iterable[int]) -> Tuple[int, ...]:
    result: List[int] = []
    for can_id in state_ids:
        result.extend(STATE_FRAME_OUTPUTS[can_id])
    return tuple(result)
