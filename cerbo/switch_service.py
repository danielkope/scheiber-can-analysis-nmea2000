#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Scheiber Multibloc V8 -> native Victron SwitchableOutput service.

Publishes the ten logical controls from the sailing panel as
``com.victronenergy.switch.scheiber``. Accepted D-Bus writes are converted to
captured-style 0x04001808 momentary panel-key events, then confirmed from the
authoritative Scheiber output-state frames before the transaction completes.

No direct output-forcing frame is used. Physical state always starts UNKNOWN.
"""
from __future__ import annotations

import json
import os
import signal
import socket
import struct
import sys
import time
from dataclasses import dataclass
from datetime import datetime
from functools import partial
from typing import Dict, List, Optional

APP_DIR = os.path.dirname(os.path.abspath(__file__))
if APP_DIR not in sys.path:
    sys.path.insert(0, APP_DIR)

for candidate in (
    "/opt/victronenergy/dbus-systemcalc-py/ext/velib_python",
    "/opt/victronenergy/dbus_generator/ext/velib_python",
    "/opt/victronenergy/dbus-generator/ext/velib_python",
    "/opt/victronenergy/velib_python",
):
    if os.path.isfile(os.path.join(candidate, "vedbus.py")):
        sys.path.insert(0, candidate)
        break
else:
    for root, _dirs, files in os.walk("/opt/victronenergy"):
        if "vedbus.py" in files:
            sys.path.insert(0, root)
            break

import dbus  # type: ignore  # noqa: E402
from dbus.mainloop.glib import DBusGMainLoop  # type: ignore  # noqa: E402
from gi.repository import GLib  # type: ignore  # noqa: E402
from vedbus import VeDbusService  # type: ignore  # noqa: E402

from scheiber_switch_protocol import (  # noqa: E402
    CHANNELS,
    CHANNEL_BY_ID,
    DIGITAL_INPUT_ID,
    KIND_BILGE,
    KIND_BINARY,
    MODE_AUTO,
    MODE_INVALID,
    MODE_MANUAL,
    MODE_OFF,
    MODE_UNKNOWN,
    PANEL_ALIVE_ID,
    STATE_IDS,
    SWITCH_EVENT_ID,
    Channel,
    CommandStep,
    InvalidStateError,
    StateModel,
    UnknownStateError,
    bilge_mode_to_dbus,
    build_key_payloads,
    plan_bilge,
    plan_binary,
)

DBusGMainLoop(set_as_default=True)

SERVICE_VERSION = "0.1.0"
SERVICE_NAME = "com.victronenergy.switch.scheiber"
DEVICE_INSTANCE = 55
PRODUCT_ID = 0xFFFF
PRODUCT_NAME = "Scheiber V8 Switchboard"

CAN_IF = os.environ.get("CAN_IF", "can2")
TX_ENABLED = os.environ.get("SWITCH_TX_ENABLED", "1").strip().lower() not in ("0", "false", "no", "off")
RTR_ENABLED = os.environ.get("SWITCH_RTR_ENABLED", "1").strip().lower() not in ("0", "false", "no", "off")
PRESS_SECONDS = float(os.environ.get("SWITCH_PRESS_SECONDS", "0.150"))
COMMAND_TIMEOUT = float(os.environ.get("SWITCH_COMMAND_TIMEOUT", "4.0"))
PANEL_STALE_SECONDS = float(os.environ.get("SWITCH_PANEL_STALE", "5.0"))
RTR_RETRY_SECONDS = float(os.environ.get("SWITCH_RTR_RETRY", "2.0"))
RTR_MAX_ATTEMPTS = int(os.environ.get("SWITCH_RTR_ATTEMPTS", "5"))

DATA_DIR = os.environ.get("SCHEIBER_DATA_DIR", "/data/scheiber-gx")
LOGFILE = os.path.join(DATA_DIR, "switch.log")
STATUSFILE = os.path.join(DATA_DIR, "switch-status.json")
SETTINGSFILE = os.path.join(DATA_DIR, "switch-settings.json")

MODULE_STATE_CONNECTED = 0x100
MODULE_STATE_CHANNEL_FAULT = 0x103
STATUS_OFF = 0x00
STATUS_POWERED = 0x01
STATUS_OUTPUT_FAULT = 0x08
STATUS_ON = 0x09
STATUS_DISABLED = 0x20
OUTPUT_FUNCTION_MANUAL = 2
SWITCH_MODE_SWITCHING = 2
GENERIC_INPUT_TYPE_DISCRETE = 0
GENERIC_INPUT_STATUS_OK = 0
GENERIC_INPUT_STATUS_FAULT = 1
GENERIC_DIGITAL_INPUT_MODE_ON_OFF = 3

CAN_EFF_FLAG = 0x80000000
CAN_RTR_FLAG = 0x40000000
CAN_EFF_MASK = 0x1FFFFFFF
SOL_CAN_RAW = getattr(socket, "SOL_CAN_RAW", 101)
CAN_RAW_FILTER = getattr(socket, "CAN_RAW_FILTER", 1)
CAN_RAW_RECV_OWN_MSGS = getattr(socket, "CAN_RAW_RECV_OWN_MSGS", 4)
CAN_FRAME = struct.Struct("=IB3x8s")
FILTER_IDS = (PANEL_ALIVE_ID, DIGITAL_INPUT_ID, *STATE_IDS, SWITCH_EVENT_ID)

RUNNING_INPUTS = (
    ("fresh_water_pump_running", "Fresh Water Pump Running", "Pumps"),
    ("bilge_port_running", "Port Bilge Pump Running", "Pumps"),
    ("bilge_starboard_running", "Starboard Bilge Pump Running", "Pumps"),
)


@dataclass
class PendingCommand:
    channel_id: str
    target_state: int
    target_auto: Optional[int]
    steps: List[CommandStep]
    started: float
    step_index: int = 0
    step_started: float = 0.0
    release_sent: bool = False

    @property
    def active_step(self) -> CommandStep:
        return self.steps[self.step_index]


class ScheiberSwitchService:
    def __init__(self) -> None:
        os.makedirs(DATA_DIR, exist_ok=True)
        self.model = StateModel()
        self.auto_preferences = self.load_settings()
        self.service: Optional[VeDbusService] = None
        self.can_socket: Optional[socket.socket] = None
        self.can_watch_id: Optional[int] = None
        self.connected = False
        self.last_panel_activity: Optional[float] = None
        self.last_alive: Optional[float] = None
        self.pending: Optional[PendingCommand] = None
        self.faulted_channels = set()
        self.last_command_error: Dict[str, str] = {channel.channel_id: "" for channel in CHANNELS}
        self.rtr_attempts = 0
        self.next_rtr_at = 0.0
        self.last_missing_count = len(STATE_IDS)
        self.last_status_write = 0.0

        self.log("=" * 64)
        self.log(f"Scheiber native switch service V{SERVICE_VERSION}")
        self.log(f"D-Bus service : {SERVICE_NAME}")
        self.log(f"CAN interface : {CAN_IF}")
        self.log(f"CAN commands  : {'ENABLED' if TX_ENABLED else 'DISABLED'}")
        self.log(f"RTR sync      : {'ENABLED' if RTR_ENABLED else 'DISABLED'}")
        self.log("Control method: 0x04001808 momentary key events; no direct output forcing")
        self.log("=" * 64)

        self.setup_dbus()
        self.connect_can()
        GLib.timeout_add(100, self.timer_tick)
        GLib.timeout_add(400, self.initial_sync)
        self.write_status()

    def log(self, message: str) -> None:
        line = f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} {message}\n"
        print(line, end="", flush=True)
        try:
            with open(LOGFILE, "a", encoding="utf-8") as handle:
                handle.write(line)
        except Exception:
            pass

    def load_settings(self) -> Dict[str, bool]:
        result = {channel.channel_id: False for channel in CHANNELS if channel.persisted_auto}
        try:
            with open(SETTINGSFILE, "r", encoding="utf-8") as handle:
                raw = json.load(handle)
            stored = raw.get("auto", {}) if isinstance(raw, dict) else {}
            for channel_id in result:
                if channel_id in stored:
                    result[channel_id] = bool(stored[channel_id])
        except FileNotFoundError:
            pass
        except Exception as exc:
            self.log(f"WARNING: could not load {SETTINGSFILE}: {exc}")
        return result

    def save_settings(self) -> None:
        payload = {
            "schema_version": 1,
            "auto": dict(sorted(self.auto_preferences.items())),
            "updated": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        }
        temporary = SETTINGSFILE + ".tmp"
        try:
            with open(temporary, "w", encoding="utf-8") as handle:
                json.dump(payload, handle, indent=2, sort_keys=True)
                handle.write("\n")
            os.replace(temporary, SETTINGSFILE)
        except Exception as exc:
            self.log(f"WARNING: could not save {SETTINGSFILE}: {exc}")

    def write_status(self) -> None:
        pending = None
        if self.pending is not None:
            pending = {
                "channel": self.pending.channel_id,
                "target_state": self.pending.target_state,
                "target_auto": self.pending.target_auto,
                "step": self.pending.step_index + 1,
                "steps": len(self.pending.steps),
                "active": self.pending.active_step.description,
                "release_sent": self.pending.release_sent,
            }
        payload = {
            "service": SERVICE_NAME,
            "version": SERVICE_VERSION,
            "can_interface": CAN_IF,
            "connected": self.connected,
            "tx_enabled": TX_ENABLED,
            "rtr_enabled": RTR_ENABLED,
            "rtr_attempts": self.rtr_attempts,
            "missing_state_ids": [f"0x{can_id:08X}" for can_id in self.model.missing_state_ids()],
            "pending": pending,
            "faulted_channels": sorted(self.faulted_channels),
            "last_command_error": dict(self.last_command_error),
            "auto_preferences": dict(self.auto_preferences),
            "state": self.model.snapshot(),
            "updated": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        }
        temporary = STATUSFILE + ".tmp"
        try:
            with open(temporary, "w", encoding="utf-8") as handle:
                json.dump(payload, handle, indent=2, sort_keys=True)
                handle.write("\n")
            os.replace(temporary, STATUSFILE)
        except Exception as exc:
            self.log(f"WARNING: could not write {STATUSFILE}: {exc}")

    @staticmethod
    def output_base(channel: Channel) -> str:
        return f"/SwitchableOutput/{channel.channel_id}"

    @staticmethod
    def input_base(signal_name: str) -> str:
        return f"/GenericInput/{signal_name}"

    def setup_dbus(self) -> None:
        service = VeDbusService(SERVICE_NAME, register=False)
        service.add_mandatory_paths(
            processname=os.path.abspath(__file__),
            processversion=SERVICE_VERSION,
            connection=f"Scheiber CAN on {CAN_IF}",
            deviceinstance=DEVICE_INSTANCE,
            productid=PRODUCT_ID,
            productname=PRODUCT_NAME,
            firmwareversion=SERVICE_VERSION,
            hardwareversion=None,
            connected=0,
        )
        service.add_path("/CustomName", PRODUCT_NAME)
        service.add_path("/Serial", f"scheiber-switch-{CAN_IF}")
        service.add_path("/Model", "Scheiber Multibloc V8 sailing switchboard")
        service.add_path("/State", MODULE_STATE_CHANNEL_FAULT)

        for channel in CHANNELS:
            base = self.output_base(channel)
            service.add_path(f"{base}/Name", channel.display_name)
            service.add_path(
                f"{base}/State", 0, writeable=True,
                onchangecallback=partial(self.on_state_write, channel.channel_id),
            )
            service.add_path(f"{base}/Status", STATUS_DISABLED)
            service.add_path(f"{base}/Settings/CustomName", "")
            service.add_path(f"{base}/Settings/Group", channel.group)
            service.add_path(f"{base}/Settings/ShowUIControl", 1)
            service.add_path(f"{base}/Settings/Type", channel.ui_type)
            service.add_path(f"{base}/Settings/ValidTypes", 1 << channel.ui_type)
            service.add_path(f"{base}/Settings/Function", OUTPUT_FUNCTION_MANUAL)
            service.add_path(f"{base}/Settings/ValidFunctions", 1 << OUTPUT_FUNCTION_MANUAL)
            service.add_path(f"{base}/Settings/SwitchMode", SWITCH_MODE_SWITCHING)
            if channel.ui_type == 9:
                initial_auto = int(self.auto_preferences.get(channel.channel_id, False)) if channel.persisted_auto else 0
                service.add_path(
                    f"{base}/Auto", initial_auto, writeable=True,
                    onchangecallback=partial(self.on_auto_write, channel.channel_id),
                )
            service.add_path(f"{base}/Scheiber/Known", 0)
            service.add_path(f"{base}/Scheiber/Mode", MODE_UNKNOWN)
            service.add_path(f"{base}/Scheiber/Running", 0)
            service.add_path(f"{base}/Scheiber/RunningKnown", 0)
            service.add_path(f"{base}/Scheiber/CommandPending", 0)
            service.add_path(f"{base}/Scheiber/LastCommandError", "")

        for signal_name, display_name, group in RUNNING_INPUTS:
            base = self.input_base(signal_name)
            service.add_path(f"{base}/Name", display_name)
            service.add_path(f"{base}/Value", 0)
            service.add_path(f"{base}/Status", GENERIC_INPUT_STATUS_FAULT)
            service.add_path(f"{base}/Settings/CustomName", "")
            service.add_path(f"{base}/Settings/Group", group)
            service.add_path(f"{base}/Settings/ShowUIInput", 1)
            service.add_path(f"{base}/Settings/Type", GENERIC_INPUT_TYPE_DISCRETE)
            service.add_path(f"{base}/Settings/ValidTypes", 1)
            service.add_path(f"{base}/Settings/Labels", ["Not running", "Running"])
            service.add_path(f"{base}/Settings/Invert", 0)
            service.add_path(f"{base}/Settings/DigitalInputMode", GENERIC_DIGITAL_INPUT_MODE_ON_OFF)

        service.add_path("/Scheiber/CanInterface", CAN_IF)
        service.add_path("/Scheiber/TxEnabled", int(TX_ENABLED))
        service.add_path("/Scheiber/RtrEnabled", int(RTR_ENABLED))
        service.add_path("/Scheiber/PanelAlive", 0)
        service.add_path("/Scheiber/SynchronizedOutputCount", 0)
        service.add_path("/Scheiber/SynchronizedOutputs", "")
        service.add_path("/Scheiber/PendingCommand", "")
        service.add_path("/Scheiber/LastError", "")
        service.add_path(
            "/Scheiber/FeedbackConfidence",
            "Water running demand-confirmed; bilge running confirmed in MANUAL and pending AUTO field validation",
        )
        service.add_path(
            "/Scheiber/ControlMethod",
            "0x04001808 momentary key emulation; no direct output forcing",
        )
        service.register()
        self.service = service
        self.log(f"Registered {SERVICE_NAME}")
        self.refresh_dbus()

    def on_state_write(self, channel_id: str, _path: str, value: object) -> bool:
        try:
            requested = int(value)
        except Exception:
            return self.reject(channel_id, f"invalid State value {value!r}")
        if requested not in (0, 1):
            return self.reject(channel_id, "State must be 0 or 1")
        channel = CHANNEL_BY_ID[channel_id]
        if channel.kind == KIND_BILGE:
            return self.request_bilge(channel, MODE_MANUAL if requested else MODE_OFF)
        return self.request_binary(channel, bool(requested))

    def on_auto_write(self, channel_id: str, _path: str, value: object) -> bool:
        try:
            requested = int(value)
        except Exception:
            return self.reject(channel_id, f"invalid Auto value {value!r}")
        if requested not in (0, 1):
            return self.reject(channel_id, "Auto must be 0 or 1")
        channel = CHANNEL_BY_ID[channel_id]
        if channel.persisted_auto:
            self.auto_preferences[channel_id] = bool(requested)
            self.save_settings()
            self.last_command_error[channel_id] = ""
            self.log(f"Automation ownership {channel_id} -> {'AUTO' if requested else 'MANUAL'}")
            return True
        if channel.kind != KIND_BILGE:
            return self.reject(channel_id, "Auto is unsupported for this channel")
        return self.request_bilge(channel, MODE_AUTO if requested else MODE_OFF)

    def validate_command(self, channel: Channel) -> bool:
        if not self.connected:
            return self.reject(channel.channel_id, "panel is not connected")
        if not self.model.channel_known(channel):
            return self.reject(channel.channel_id, "physical state is UNKNOWN; wait for CAN synchronization")
        if self.pending is not None:
            return self.reject(channel.channel_id, f"command in progress for {self.pending.channel_id}")
        return True

    def request_binary(self, channel: Channel, target: bool) -> bool:
        if not self.validate_command(channel):
            return False
        try:
            steps = plan_binary(channel, self.model.binary_state(channel), target)
        except (UnknownStateError, InvalidStateError, ValueError) as exc:
            return self.reject(channel.channel_id, str(exc))
        target_auto = int(self.auto_preferences.get(channel.channel_id, False)) if channel.persisted_auto else None
        return self.begin_command(channel, int(target), target_auto, steps)

    def request_bilge(self, channel: Channel, target_mode: str) -> bool:
        if not self.validate_command(channel):
            return False
        try:
            steps = plan_bilge(
                channel,
                self.model.outputs[int(channel.auto_output)],
                self.model.outputs[int(channel.manual_output)],
                target_mode,
            )
            target_state, target_auto = bilge_mode_to_dbus(target_mode)
        except (UnknownStateError, InvalidStateError, ValueError) as exc:
            return self.reject(channel.channel_id, str(exc))
        return self.begin_command(channel, target_state, target_auto, steps)

    def begin_command(self, channel: Channel, target_state: int, target_auto: Optional[int],
                      steps: List[CommandStep]) -> bool:
        self.last_command_error[channel.channel_id] = ""
        self.faulted_channels.discard(channel.channel_id)
        if not steps:
            self.log(f"No CAN command needed for {channel.channel_id}; already at target")
            self.refresh_channel(channel)
            return True
        if not TX_ENABLED:
            return self.reject(channel.channel_id, "CAN transmission is disabled")
        self.pending = PendingCommand(channel.channel_id, target_state, target_auto, steps, time.monotonic())
        self.update_pending_paths()
        return self.start_pending_step()

    def reject(self, channel_id: str, reason: str) -> bool:
        self.last_command_error[channel_id] = reason
        self.log(f"REJECTED {channel_id}: {reason}")
        if self.service is not None:
            self.service[f"{self.output_base(CHANNEL_BY_ID[channel_id])}/Scheiber/LastCommandError"] = reason
            self.service["/Scheiber/LastError"] = f"{channel_id}: {reason}"
        return False

    def connect_can(self) -> None:
        can_socket = socket.socket(socket.PF_CAN, socket.SOCK_RAW, socket.CAN_RAW)
        can_socket.setblocking(False)
        filters = b"".join(
            struct.pack("=II", can_id | CAN_EFF_FLAG, CAN_EFF_MASK | CAN_EFF_FLAG | CAN_RTR_FLAG)
            for can_id in FILTER_IDS
        )
        can_socket.setsockopt(SOL_CAN_RAW, CAN_RAW_FILTER, filters)
        try:
            can_socket.setsockopt(SOL_CAN_RAW, CAN_RAW_RECV_OWN_MSGS, struct.pack("=I", 0))
        except OSError:
            pass
        can_socket.bind((CAN_IF,))
        self.can_socket = can_socket
        self.can_watch_id = GLib.io_add_watch(
            can_socket.fileno(), GLib.IO_IN | GLib.IO_ERR | GLib.IO_HUP, self.on_can_io
        )
        self.log(f"SocketCAN connected to {CAN_IF}")

    def on_can_io(self, _source: int, condition: GLib.IOCondition) -> bool:
        if condition & (GLib.IO_ERR | GLib.IO_HUP):
            self.log(f"FATAL: SocketCAN watch condition {int(condition)}")
            GLib.idle_add(self.exit_with_error)
            return False
        assert self.can_socket is not None
        while True:
            try:
                raw = self.can_socket.recv(CAN_FRAME.size)
            except BlockingIOError:
                break
            except OSError as exc:
                self.log(f"FATAL: SocketCAN receive failed: {exc}")
                GLib.idle_add(self.exit_with_error)
                return False
            if len(raw) != CAN_FRAME.size:
                continue
            raw_id, dlc, raw_data = CAN_FRAME.unpack(raw)
            if not raw_id & CAN_EFF_FLAG or raw_id & CAN_RTR_FLAG:
                continue
            self.handle_can(raw_id & CAN_EFF_MASK, raw_data[: min(int(dlc), 8)])
        return True

    @staticmethod
    def exit_with_error() -> bool:
        os._exit(1)

    def handle_can(self, can_id: int, data: bytes) -> None:
        if can_id not in FILTER_IDS:
            return
        now = time.monotonic()
        self.last_panel_activity = now
        if can_id == PANEL_ALIVE_ID:
            self.last_alive = now
        if not self.connected:
            self.set_connected(True)
        try:
            changed_outputs, changed_running = self.model.apply(can_id, data)
        except ValueError as exc:
            message = f"ignored malformed CAN frame 0x{can_id:08X} ({data.hex().upper()}): {exc}"
            self.log(f"WARNING: {message}")
            if self.service is not None:
                self.service["/Scheiber/LastError"] = message
            return
        if changed_outputs:
            rendered = ", ".join(
                f"{number}={'ON' if self.model.outputs[number] else 'OFF'}" for number in changed_outputs
            )
            self.log(f"CAN output state: {rendered}")
            missing_count = len(self.model.missing_state_ids())
            if missing_count < self.last_missing_count:
                self.rtr_attempts = 0
                self.next_rtr_at = now + 0.3
                self.last_missing_count = missing_count
        if changed_running:
            rendered = ", ".join(
                f"{name}={'RUNNING' if self.model.running[name] else 'STOPPED'}" for name in changed_running
            )
            self.log(f"CAN pump feedback: {rendered}")
        if changed_outputs or changed_running or can_id == PANEL_ALIVE_ID:
            self.refresh_dbus()
        self.advance_pending_if_ready()

    def send_can(self, can_id: int, data: bytes = b"", remote: bool = False, dlc: Optional[int] = None) -> None:
        if self.can_socket is None:
            raise OSError("SocketCAN is not connected")
        payload = bytes(data)
        if len(payload) > 8:
            raise ValueError("classical CAN payload exceeds 8 bytes")
        frame_dlc = len(payload) if dlc is None else int(dlc)
        if not 0 <= frame_dlc <= 8:
            raise ValueError("CAN DLC must be 0..8")
        raw_id = int(can_id) | CAN_EFF_FLAG | (CAN_RTR_FLAG if remote else 0)
        self.can_socket.send(CAN_FRAME.pack(raw_id, frame_dlc, payload.ljust(8, b"\x00")))

    def initial_sync(self) -> bool:
        self.query_missing_states(force=True)
        return False

    def query_missing_states(self, force: bool = False) -> None:
        if not RTR_ENABLED or self.can_socket is None:
            return
        now = time.monotonic()
        if not force and now < self.next_rtr_at:
            return
        missing = self.model.missing_state_ids()
        if not missing or self.rtr_attempts >= RTR_MAX_ATTEMPTS:
            return
        self.rtr_attempts += 1
        self.next_rtr_at = now + RTR_RETRY_SECONDS
        self.log(
            f"RTR state sync attempt {self.rtr_attempts}: "
            + ", ".join(f"0x{can_id:08X}" for can_id in missing)
        )
        for can_id in missing:
            try:
                self.send_can(can_id, remote=True, dlc=8)
            except Exception as exc:
                message = f"RTR state query 0x{can_id:08X} failed: {exc}"
                self.log(f"FATAL: {message}")
                if self.service is not None:
                    self.service["/Scheiber/LastError"] = message
                GLib.idle_add(self.exit_with_error)
                return
            time.sleep(0.03)

    def start_pending_step(self) -> bool:
        if self.pending is None:
            return False
        step = self.pending.active_step
        press, _release = build_key_payloads(step.key_code)
        try:
            self.send_can(SWITCH_EVENT_ID, press)
        except Exception as exc:
            self.fail_pending(f"failed to send key press: {exc}")
            return False
        self.pending.step_started = time.monotonic()
        self.pending.release_sent = False
        self.log(
            f"CAN key press {step.key_name} (0x{step.key_code:02X}) "
            f"step {self.pending.step_index + 1}/{len(self.pending.steps)}: {step.description}"
        )
        GLib.timeout_add(
            max(1, int(PRESS_SECONDS * 1000)),
            self.send_pending_release,
            self.pending.channel_id,
            self.pending.step_index,
            step.key_code,
        )
        return True

    def send_pending_release(self, channel_id: str, step_index: int, key_code: int) -> bool:
        if self.pending is None or self.pending.channel_id != channel_id or self.pending.step_index != step_index:
            return False
        _press, release = build_key_payloads(key_code)
        try:
            self.send_can(SWITCH_EVENT_ID, release)
        except Exception as exc:
            self.fail_pending(f"failed to send key release: {exc}")
            return False
        self.pending.release_sent = True
        self.log(f"CAN key release 0x{key_code:02X}")
        self.advance_pending_if_ready()
        return False

    def advance_pending_if_ready(self) -> None:
        if self.pending is None or not self.pending.release_sent:
            return
        if not self.pending.active_step.satisfied(self.model.outputs):
            return
        self.pending.step_index += 1
        if self.pending.step_index >= len(self.pending.steps):
            channel_id = self.pending.channel_id
            elapsed = time.monotonic() - self.pending.started
            self.pending = None
            self.faulted_channels.discard(channel_id)
            self.last_command_error[channel_id] = ""
            self.log(f"CAN command confirmed for {channel_id} in {elapsed:.3f} s")
            self.update_pending_paths()
            self.refresh_dbus()
            self.write_status()
            return
        self.update_pending_paths()
        self.start_pending_step()

    def fail_pending(self, reason: str) -> None:
        if self.pending is None:
            return
        channel_id = self.pending.channel_id
        self.log(f"COMMAND FAULT {channel_id}: {reason}")
        self.faulted_channels.add(channel_id)
        self.last_command_error[channel_id] = reason
        self.pending = None
        if self.service is not None:
            self.service["/Scheiber/LastError"] = f"{channel_id}: {reason}"
        self.update_pending_paths()
        self.refresh_dbus()
        self.write_status()

    def set_connected(self, connected: bool) -> None:
        connected = bool(connected)
        if self.connected == connected:
            return
        self.connected = connected
        if not connected:
            if self.pending is not None:
                self.fail_pending("panel communication lost")
            self.model.reset_unknown()
            self.rtr_attempts = 0
            self.last_missing_count = len(STATE_IDS)
            self.next_rtr_at = time.monotonic() + 0.5
            self.log("Scheiber panel disconnected; all switch states are UNKNOWN")
        else:
            self.rtr_attempts = 0
            self.next_rtr_at = time.monotonic() + 0.2
            self.log("Scheiber panel activity detected")
        self.refresh_dbus()

    def channel_status(self, channel: Channel) -> int:
        if channel.channel_id in self.faulted_channels:
            return STATUS_OUTPUT_FAULT
        if not self.connected or not self.model.channel_known(channel):
            return STATUS_DISABLED
        if channel.kind == KIND_BINARY:
            enabled = bool(self.model.binary_state(channel))
            if channel.running_signal is None:
                return STATUS_ON if enabled else STATUS_OFF
            running = self.model.running_state(channel)
            if running is True:
                return STATUS_ON
            return STATUS_POWERED if enabled else STATUS_OFF
        mode = self.model.bilge_mode(channel)
        if mode == MODE_INVALID:
            return STATUS_OUTPUT_FAULT
        if mode == MODE_UNKNOWN:
            return STATUS_DISABLED
        if self.model.running_state(channel) is True:
            return STATUS_ON
        return STATUS_OFF if mode == MODE_OFF else STATUS_POWERED

    def refresh_channel(self, channel: Channel) -> None:
        if self.service is None:
            return
        base = self.output_base(channel)
        known = self.connected and self.model.channel_known(channel)
        self.service[f"{base}/Scheiber/Known"] = int(known)
        self.service[f"{base}/Status"] = self.channel_status(channel)
        self.service[f"{base}/Scheiber/CommandPending"] = int(
            self.pending is not None and self.pending.channel_id == channel.channel_id
        )
        self.service[f"{base}/Scheiber/LastCommandError"] = self.last_command_error[channel.channel_id]
        running = self.model.running_state(channel)
        self.service[f"{base}/Scheiber/Running"] = int(bool(running))
        self.service[f"{base}/Scheiber/RunningKnown"] = int(running is not None and self.connected)
        if not known:
            self.service[f"{base}/State"] = 0
            if channel.ui_type == 9:
                self.service[f"{base}/Auto"] = (
                    int(self.auto_preferences.get(channel.channel_id, False)) if channel.persisted_auto else 0
                )
            self.service[f"{base}/Scheiber/Mode"] = MODE_UNKNOWN
            return
        if channel.kind == KIND_BINARY:
            state = int(bool(self.model.binary_state(channel)))
            self.service[f"{base}/State"] = state
            if channel.persisted_auto:
                auto = int(self.auto_preferences.get(channel.channel_id, False))
                self.service[f"{base}/Auto"] = auto
                mode = MODE_AUTO if auto else ("ON" if state else MODE_OFF)
            else:
                mode = "ON" if state else MODE_OFF
            self.service[f"{base}/Scheiber/Mode"] = mode
            return
        mode = self.model.bilge_mode(channel)
        self.service[f"{base}/Scheiber/Mode"] = mode
        if mode in (MODE_OFF, MODE_AUTO, MODE_MANUAL):
            state, auto = bilge_mode_to_dbus(mode)
            self.service[f"{base}/State"] = state
            self.service[f"{base}/Auto"] = auto
        elif mode == MODE_INVALID:
            self.service[f"{base}/State"] = int(bool(self.model.outputs[int(channel.manual_output)]))
            self.service[f"{base}/Auto"] = 0

    def refresh_running_inputs(self) -> None:
        if self.service is None:
            return
        for signal_name, _display_name, _group in RUNNING_INPUTS:
            base = self.input_base(signal_name)
            value = self.model.running[signal_name]
            self.service[f"{base}/Value"] = int(bool(value))
            self.service[f"{base}/Status"] = (
                GENERIC_INPUT_STATUS_OK if value is not None and self.connected else GENERIC_INPUT_STATUS_FAULT
            )

    def update_pending_paths(self) -> None:
        if self.service is None:
            return
        text = "" if self.pending is None else f"{self.pending.channel_id}: {self.pending.active_step.description}"
        self.service["/Scheiber/PendingCommand"] = text
        for channel in CHANNELS:
            self.service[f"{self.output_base(channel)}/Scheiber/CommandPending"] = int(
                self.pending is not None and self.pending.channel_id == channel.channel_id
            )

    def refresh_dbus(self) -> None:
        if self.service is None:
            return
        self.service["/Connected"] = int(self.connected)
        self.service["/State"] = MODULE_STATE_CONNECTED if self.connected else MODULE_STATE_CHANNEL_FAULT
        self.service["/Scheiber/PanelAlive"] = int(
            self.connected and self.last_alive is not None
            and time.monotonic() - self.last_alive <= PANEL_STALE_SECONDS
        )
        synchronized = self.model.synchronized_outputs()
        self.service["/Scheiber/SynchronizedOutputCount"] = len(synchronized)
        self.service["/Scheiber/SynchronizedOutputs"] = ",".join(str(number) for number in synchronized)
        for channel in CHANNELS:
            self.refresh_channel(channel)
        self.refresh_running_inputs()
        self.update_pending_paths()

    def timer_tick(self) -> bool:
        now = time.monotonic()
        if self.connected and self.last_panel_activity is not None and now - self.last_panel_activity > PANEL_STALE_SECONDS:
            self.set_connected(False)
        if self.pending is not None and now - self.pending.step_started > COMMAND_TIMEOUT:
            self.fail_pending(f"no matching output-state feedback within {COMMAND_TIMEOUT:.1f} s")
        self.query_missing_states()
        if now - self.last_status_write >= 5.0:
            self.last_status_write = now
            self.write_status()
        return True

    def close(self) -> None:
        self.write_status()
        if self.can_watch_id is not None:
            try:
                GLib.source_remove(self.can_watch_id)
            except Exception:
                pass
            self.can_watch_id = None
        if self.can_socket is not None:
            try:
                self.can_socket.close()
            except Exception:
                pass
            self.can_socket = None


def main() -> int:
    service = ScheiberSwitchService()
    loop = GLib.MainLoop()

    def stop(_signum: int, _frame: object) -> None:
        loop.quit()

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    try:
        loop.run()
    finally:
        service.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
