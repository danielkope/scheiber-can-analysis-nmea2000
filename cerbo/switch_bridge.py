#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Scheiber V8 control-panel <-> native Victron SwitchableOutput bridge.

Safety/control rules:
* Only captured-style SFSP panel key events (0x04001808) are transmitted.
* The source-derived direct output command (CMD_S_TOR) is deliberately unused.
* Every controlled output starts UNKNOWN and D-Bus writes are rejected until
  matching 02xx1808 state feedback has synchronized the physical state.
* Key commands are momentary toggles. A key is emitted only when known physical
  state differs from the requested state/mode.
* Commands are confirmed from physical state feedback and are never retried.
* Bilge OFF/AUTO/MANUAL is modeled from the two Scheiber mode outputs. The
  unobserved AUTO=0/MANUAL=1 combination is treated as invalid.
* Bilge and freshwater /Status use the independent 0x02141808 actual-running
  feedback. Bilge running bits are high-confidence from MANUAL tests and are
  expected to remain actual-running feedback in AUTO; an AUTO pumping capture
  is still a field-validation item.
"""

from __future__ import annotations

import json
import os
import socket
import struct
import sys
import time
from datetime import datetime

# Find Victron velib_python, matching the existing Cerbo bridge approach.
for p in (
    "/opt/victronenergy/dbus-systemcalc-py/ext/velib_python",
    "/opt/victronenergy/dbus_generator/ext/velib_python",
    "/opt/victronenergy/dbus-generator/ext/velib_python",
    "/opt/victronenergy/velib_python",
):
    if os.path.isfile(os.path.join(p, "vedbus.py")):
        sys.path.insert(0, p)
        break
else:
    for root, dirs, files in os.walk("/opt/victronenergy"):
        if "vedbus.py" in files:
            sys.path.insert(0, root)
            break

import dbus
from dbus.mainloop.glib import DBusGMainLoop
from gi.repository import GLib
from vedbus import VeDbusService

from switch_protocol import (
    ALIVE_ID,
    CHANNELS,
    CHANNEL_BY_ID,
    DIGITAL_INPUT_ID,
    KEYS,
    PANEL_PRESS_SECONDS,
    STATE_IDS,
    SWITCH_ID,
    BilgeMode,
    SwitchStateModel,
    VICTRON_STATUS_OFF,
    VICTRON_STATUS_ON,
    VICTRON_STATUS_OUTPUT_FAULT,
    VICTRON_TYPE_THREE_STATE,
    bilge_ui_values,
    build_key_frames,
    plan_bilge_transition,
    plan_binary_transition,
    relevant_can_ids,
)

DBusGMainLoop(set_as_default=True)

CAN_IF = os.environ.get("CAN_IF", "can2")
TX_ENABLED = os.environ.get("SCHEIBER_SWITCH_TX", "1").strip().lower() not in (
    "0", "false", "no", "off"
)
QUERY_STATES = os.environ.get("SCHEIBER_SWITCH_QUERY_STATES", "1").strip().lower() not in (
    "0", "false", "no", "off"
)

SERVICE_NAME = "com.victronenergy.switch.scheiber"
DEVICE_INSTANCE = int(os.environ.get("SCHEIBER_SWITCH_DEVICE_INSTANCE", "150"))
PRODUCT_ID = 0xFFFF
PRODUCT_NAME = "Scheiber V8 Switchboard"
BRIDGE_VERSION = "0.1.0"

APP_DIR = os.environ.get("APP_DIR", "/data/scheiber-switches")
LOGFILE = os.path.join(APP_DIR, "switch_bridge.log")
STATUSFILE = os.path.join(APP_DIR, "switch_status.json")

COMMAND_CONFIRM_SECONDS = float(os.environ.get("SCHEIBER_SWITCH_CONFIRM_SECONDS", "3.0"))
NEXT_ACTION_DELAY_MS = 75
STATUS_SNAPSHOT_INTERVAL = 5.0

CAN_EFF_FLAG = 0x80000000
CAN_RTR_FLAG = 0x40000000
CAN_EFF_MASK = 0x1FFFFFFF
SOL_CAN_RAW = getattr(socket, "SOL_CAN_RAW", 101)
CAN_RAW_FILTER = 1
CAN_RAW_RECV_OWN_MSGS = 4

# Native gui-v2 mock service uses Function=2 / ValidFunctions=2 for generic
# switch outputs. ValidTypes is restricted to the actual type here so users
# cannot reclassify the reverse-engineered channel in GX settings.
SWITCH_FUNCTION = 2
SWITCH_VALID_FUNCTIONS = 2


class ScheiberSwitchBridge:
    def __init__(self):
        self.model = SwitchStateModel()
        self.service = None
        self.can = None
        self.can_watch_id = None
        self.can_retry_id = None
        self.query_index = 0
        self.query_timer_id = None
        self.last_status_snapshot = 0.0

        # AUTO for anchor/water is a Cerbo automation abstraction, not a native
        # Scheiber state. It intentionally starts manual after process restart.
        self.automation_mode = {
            spec.channel_id: False for spec in CHANNELS if spec.supports_automation
        }
        self.auto_target = {
            spec.channel_id: None for spec in CHANNELS if spec.supports_automation
        }

        # Exactly one panel command sequence is allowed at a time. This makes
        # command/feedback ownership unambiguous on a toggle protocol.
        self.pending_channel = None
        self.pending_actions = []
        self.pending_action = None
        self.pending_action_confirmed = False
        self.pending_action_released = False
        self.pending_deadline = None
        self.release_timer_id = None
        self.pending_reason = ""
        self.last_error = ""
        self.state_query_sent = False

        self.log("================================================")
        self.log("Scheiber native switch bridge V{}".format(BRIDGE_VERSION))
        self.log("D-Bus service : {}".format(SERVICE_NAME))
        self.log("CAN interface : {}".format(CAN_IF))
        self.log("CAN TX        : {}".format("ENABLED" if TX_ENABLED else "DISABLED"))
        self.log("State RTR     : {}".format("ENABLED" if QUERY_STATES else "DISABLED"))
        self.log("Direct output : NEVER USED")
        self.log("================================================")

        self.setup_dbus()
        self.connect_can()
        GLib.timeout_add(100, self.timer_tick)
        self.write_status(force=True)

    def log(self, message):
        line = "{} {}\n".format(datetime.now().strftime("%Y-%m-%d %H:%M:%S"), message)
        print(line, end="", flush=True)
        try:
            os.makedirs(APP_DIR, exist_ok=True)
            with open(LOGFILE, "a", encoding="utf-8") as f:
                f.write(line)
        except Exception:
            pass

    def set_error(self, message, channel_id=None):
        self.last_error = str(message)
        self.log("ERROR: {}".format(message))
        if self.service is not None:
            # Keep operational/controller errors separate from physical output
            # status. An INVALID bilge state is mapped to OutputFault by
            # sync_channel(); a busy/timeout/unsynchronized write must not leave
            # a healthy circuit falsely faulted in the native GX UI.
            self.service["/Scheiber/LastError"] = self.last_error
        self.write_status(force=True)

    @staticmethod
    def path(channel_id, suffix):
        return "/SwitchableOutput/{}/{}".format(channel_id, suffix)

    def setup_dbus(self):
        self.service = VeDbusService(SERVICE_NAME, register=False)
        self.service.add_mandatory_paths(
            processname=os.path.abspath(__file__),
            processversion=BRIDGE_VERSION,
            connection="Scheiber V8 CAN on {}".format(CAN_IF),
            deviceinstance=DEVICE_INSTANCE,
            productid=PRODUCT_ID,
            productname=PRODUCT_NAME,
            firmwareversion=BRIDGE_VERSION,
            hardwareversion=None,
            connected=0,
        )
        self.service.add_path("/CustomName", PRODUCT_NAME)
        self.service.add_path("/Serial", "scheiber-switches-{}".format(CAN_IF))
        self.service.add_path("/Model", "Scheiber Multibloc V8 control panel")
        self.service.add_path("/State", 0)
        self.service.add_path("/Scheiber/TxEnabled", int(TX_ENABLED))
        self.service.add_path("/Scheiber/StateQueryEnabled", int(QUERY_STATES))
        self.service.add_path("/Scheiber/StateQuerySent", 0)
        self.service.add_path("/Scheiber/PanelAlive", 0)
        self.service.add_path("/Scheiber/AllOutputsSynchronized", 0)
        self.service.add_path("/Scheiber/Pending", "")
        self.service.add_path("/Scheiber/LastError", "")

        for spec in CHANNELS:
            base = "/SwitchableOutput/{}".format(spec.channel_id)
            self.service.add_path(base + "/Name", spec.name)
            self.service.add_path(base + "/Settings/CustomName", "")
            self.service.add_path(base + "/Settings/Function", SWITCH_FUNCTION)
            self.service.add_path(base + "/Settings/Group", spec.group)
            self.service.add_path(base + "/Settings/ShowUIControl", 1)
            self.service.add_path(base + "/Settings/Type", spec.ui_type)
            self.service.add_path(base + "/Settings/ValidFunctions", SWITCH_VALID_FUNCTIONS)
            self.service.add_path(base + "/Settings/ValidTypes", 1 << spec.ui_type)

            self.service.add_path(
                base + "/State",
                0,
                writeable=True,
                onchangecallback=(
                    lambda p, v, channel_id=spec.channel_id:
                    self.on_state_write(channel_id, p, v)
                ),
            )
            self.service.add_path(base + "/Status", VICTRON_STATUS_OFF)

            if spec.ui_type == VICTRON_TYPE_THREE_STATE:
                self.service.add_path(
                    base + "/Auto",
                    0,
                    writeable=True,
                    onchangecallback=(
                        lambda p, v, channel_id=spec.channel_id:
                        self.on_auto_write(channel_id, p, v)
                    ),
                )

            # Transparent diagnostics / Node-RED hooks.
            self.service.add_path(base + "/Scheiber/Synchronized", 0)
            self.service.add_path(base + "/Scheiber/Mode", "UNKNOWN")
            self.service.add_path(base + "/Scheiber/Running", 0)
            self.service.add_path(base + "/Scheiber/RunningKnown", 0)

            if spec.supports_automation:
                # Node-RED should write this while /Auto=1. Writing /State is
                # deliberately treated as a manual override and exits AUTO.
                self.service.add_path(
                    base + "/Scheiber/AutoState",
                    0,
                    writeable=True,
                    onchangecallback=(
                        lambda p, v, channel_id=spec.channel_id:
                        self.on_auto_state_write(channel_id, p, v)
                    ),
                )

        self.service.register()
        self.log("Registered {} with {} logical controls".format(SERVICE_NAME, len(CHANNELS)))

    def set_connected(self, value):
        if self.service is not None:
            connected = int(bool(value))
            self.service["/Connected"] = connected
            # gui-v2 switch-device state 0x100 means Connected.
            self.service["/State"] = 0x100 if connected else 0

    def sync_channel(self, channel_id):
        spec = CHANNEL_BY_ID[channel_id]
        base = "/SwitchableOutput/{}".format(channel_id)
        synchronized = self.model.channel_synchronized(channel_id)
        self.service[base + "/Scheiber/Synchronized"] = int(synchronized)

        if spec.auto_output is not None:
            mode = self.model.bilge_mode(channel_id)
            self.service[base + "/Scheiber/Mode"] = mode.value
            state, auto = bilge_ui_values(mode)
            if state is not None:
                self.service[base + "/State"] = state
            if auto is not None:
                self.service[base + "/Auto"] = auto
            running = self.model.running_state(channel_id)
            self.service[base + "/Scheiber/RunningKnown"] = int(running is not None)
            self.service[base + "/Scheiber/Running"] = int(bool(running)) if running is not None else 0
            if mode == BilgeMode.INVALID:
                self.service[base + "/Status"] = VICTRON_STATUS_OUTPUT_FAULT
            elif running is not None:
                self.service[base + "/Status"] = VICTRON_STATUS_ON if running else VICTRON_STATUS_OFF
            return

        actual = self.model.channel_binary_state(channel_id)
        if actual is not None:
            self.service[base + "/State"] = int(actual)

        if spec.supports_automation:
            self.service[base + "/Auto"] = int(self.automation_mode[channel_id])
            if self.auto_target[channel_id] is None and actual is not None:
                self.auto_target[channel_id] = bool(actual)
            if self.auto_target[channel_id] is not None:
                self.service[base + "/Scheiber/AutoState"] = int(self.auto_target[channel_id])

        if spec.running_signal is not None:
            running = self.model.running_state(channel_id)
            self.service[base + "/Scheiber/RunningKnown"] = int(running is not None)
            self.service[base + "/Scheiber/Running"] = int(bool(running)) if running is not None else 0
            if running is not None:
                self.service[base + "/Status"] = VICTRON_STATUS_ON if running else VICTRON_STATUS_OFF
        elif actual is not None:
            self.service[base + "/Status"] = VICTRON_STATUS_ON if actual else VICTRON_STATUS_OFF

        if spec.supports_automation:
            mode = "AUTO" if self.automation_mode[channel_id] else (
                "ON" if actual else "OFF" if actual is not None else "UNKNOWN"
            )
        else:
            mode = "ON" if actual else "OFF" if actual is not None else "UNKNOWN"
        self.service[base + "/Scheiber/Mode"] = mode

    def sync_all_channels(self):
        for spec in CHANNELS:
            self.sync_channel(spec.channel_id)
        self.service["/Scheiber/PanelAlive"] = int(self.model.panel_alive_seen)
        self.service["/Scheiber/AllOutputsSynchronized"] = int(self.model.all_outputs_synchronized())

    def on_state_write(self, channel_id, path, value):
        try:
            desired = int(value)
        except Exception:
            return False
        if desired not in (0, 1):
            return False
        if not self.model.channel_synchronized(channel_id):
            self.set_error("{} control rejected: physical state is UNKNOWN".format(channel_id), channel_id)
            return False
        if self.pending_channel is not None:
            self.set_error("{} control rejected: command already pending for {}".format(
                channel_id, self.pending_channel), channel_id)
            return False

        spec = CHANNEL_BY_ID[channel_id]
        try:
            if spec.auto_output is not None:
                current = self.model.bilge_mode(channel_id)
                target = BilgeMode.MANUAL if desired else BilgeMode.OFF
                actions = plan_bilge_transition(spec, current, target)
                # Manual ON/OFF is exclusive of GX Auto.
                self.service[self.path(channel_id, "Auto")] = 0
                return self.start_actions(channel_id, actions, "GX manual {}".format(target.value))

            # /State on an automation-capable binary channel means deliberate
            # manual override. Node-RED uses /Scheiber/AutoState instead.
            if spec.supports_automation and self.automation_mode[channel_id]:
                self.automation_mode[channel_id] = False
                self.service[self.path(channel_id, "Auto")] = 0

            actual = self.model.channel_binary_state(channel_id)
            actions = plan_binary_transition(spec, actual, bool(desired))
            return self.start_actions(channel_id, actions, "GX manual {}".format("ON" if desired else "OFF"))
        except ValueError as e:
            self.set_error("{} control rejected: {}".format(channel_id, e), channel_id)
            return False

    def on_auto_write(self, channel_id, path, value):
        try:
            desired_auto = int(value)
        except Exception:
            return False
        if desired_auto not in (0, 1):
            return False
        if not self.model.channel_synchronized(channel_id):
            self.set_error("{} AUTO rejected: physical state is UNKNOWN".format(channel_id), channel_id)
            return False
        if self.pending_channel is not None:
            self.set_error("{} AUTO rejected: command already pending for {}".format(
                channel_id, self.pending_channel), channel_id)
            return False

        spec = CHANNEL_BY_ID[channel_id]
        if spec.supports_automation:
            actual = self.model.channel_binary_state(channel_id)
            self.automation_mode[channel_id] = bool(desired_auto)
            if desired_auto:
                # Enter AUTO without changing the physical output. This avoids a
                # surprise light/pump transition merely from selecting AUTO.
                self.auto_target[channel_id] = bool(actual)
                self.service[self.path(channel_id, "Scheiber/AutoState")] = int(bool(actual))
                self.log("{} entered AUTO; initial auto target follows physical state {}".format(
                    spec.name, "ON" if actual else "OFF"))
            else:
                self.log("{} left AUTO; physical state left unchanged".format(spec.name))
            self.write_status(force=True)
            return True

        if spec.auto_output is not None:
            try:
                current = self.model.bilge_mode(channel_id)
                if desired_auto:
                    target = BilgeMode.AUTO
                else:
                    # Toggling AUTO off while currently AUTO means OFF. If the
                    # bilge is already MANUAL/OFF, /Auto=0 is already correct.
                    target = BilgeMode.OFF if current == BilgeMode.AUTO else current
                actions = plan_bilge_transition(spec, current, target)
                return self.start_actions(channel_id, actions, "GX {}".format(target.value))
            except ValueError as e:
                self.set_error("{} AUTO rejected: {}".format(channel_id, e), channel_id)
                return False

        return False

    def on_auto_state_write(self, channel_id, path, value):
        try:
            desired = int(value)
        except Exception:
            return False
        if desired not in (0, 1):
            return False
        spec = CHANNEL_BY_ID[channel_id]
        if not spec.supports_automation:
            return False
        if not self.automation_mode[channel_id]:
            self.set_error("{} AutoState rejected: channel is not in AUTO".format(channel_id), channel_id)
            return False
        if not self.model.channel_synchronized(channel_id):
            self.set_error("{} AutoState rejected: physical state is UNKNOWN".format(channel_id), channel_id)
            return False
        if self.pending_channel is not None:
            self.set_error("{} AutoState rejected: command already pending for {}".format(
                channel_id, self.pending_channel), channel_id)
            return False
        try:
            actual = self.model.channel_binary_state(channel_id)
            actions = plan_binary_transition(spec, actual, bool(desired))
            self.auto_target[channel_id] = bool(desired)
            return self.start_actions(channel_id, actions, "AUTO target {}".format("ON" if desired else "OFF"))
        except ValueError as e:
            self.set_error("{} AutoState rejected: {}".format(channel_id, e), channel_id)
            return False

    def start_actions(self, channel_id, actions, reason):
        if not actions:
            self.log("{}: no CAN action required ({})".format(channel_id, reason))
            self.sync_channel(channel_id)
            return True
        if not TX_ENABLED:
            self.set_error("{} control rejected: CAN TX disabled".format(channel_id), channel_id)
            return False
        if self.can is None:
            self.set_error("{} control rejected: CAN interface disconnected".format(channel_id), channel_id)
            return False
        if self.pending_channel is not None:
            return False

        self.pending_channel = channel_id
        self.pending_actions = list(actions)
        self.pending_reason = str(reason)
        self.service["/Scheiber/Pending"] = "{}: {}".format(channel_id, reason)
        self.log("{} command accepted: {} ({} action{})".format(
            channel_id, reason, len(actions), "" if len(actions) == 1 else "s"))
        return self.start_next_action()

    def start_next_action(self):
        if not self.pending_actions:
            self.complete_sequence()
            return True
        action = self.pending_actions[0]
        self.pending_action = action
        self.pending_action_confirmed = self.action_is_confirmed(action)
        self.pending_action_released = False
        self.pending_deadline = time.monotonic() + COMMAND_CONFIRM_SECONDS

        sent = []
        for key_name in action.keys:
            press, release = build_key_frames(key_name)
            if not self.send_can_data(SWITCH_ID, press):
                for sent_key in sent:
                    _, sent_release = build_key_frames(sent_key)
                    self.send_can_data(SWITCH_ID, sent_release, best_effort=True)
                self.fail_sequence("CAN TX failed while pressing {}".format("+".join(action.keys)))
                return False
            sent.append(key_name)

        self.log("PRESSED {} [{}]".format("+".join(action.keys), action.description))
        self.release_timer_id = GLib.timeout_add(
            max(1, int(PANEL_PRESS_SECONDS * 1000)), self.release_current_action
        )
        self.write_status(force=True)
        return True

    def release_current_action(self):
        self.release_timer_id = None
        action = self.pending_action
        if action is None:
            return False
        ok = True
        for key_name in action.keys:
            press, release = build_key_frames(key_name)
            if not self.send_can_data(SWITCH_ID, release):
                ok = False
        self.pending_action_released = True
        self.log("RELEASED {}".format("+".join(action.keys)))
        if not ok:
            self.fail_sequence("CAN TX failed while releasing {}".format("+".join(action.keys)))
            return False
        if self.pending_action_confirmed:
            self.complete_current_action()
        return False

    def action_is_confirmed(self, action):
        if action.expected_output is not None:
            output, desired = action.expected_output
            actual = self.model.output(output)
            return actual is not None and actual == desired
        if action.expected_bilge_mode is not None and self.pending_channel:
            return self.model.bilge_mode(self.pending_channel) == action.expected_bilge_mode
        return False

    def check_pending_confirmation(self):
        if self.pending_action is None:
            return
        if self.action_is_confirmed(self.pending_action):
            if not self.pending_action_confirmed:
                self.pending_action_confirmed = True
                self.log("CONFIRMED {} [{}]".format(
                    self.pending_channel, self.pending_action.description))
            if self.pending_action_released:
                self.complete_current_action()

    def complete_current_action(self):
        if not self.pending_actions:
            self.complete_sequence()
            return
        self.pending_actions.pop(0)
        self.pending_action = None
        self.pending_action_confirmed = False
        self.pending_action_released = False
        self.pending_deadline = None
        if self.pending_actions:
            GLib.timeout_add(NEXT_ACTION_DELAY_MS, self._start_next_action_timer)
        else:
            self.complete_sequence()

    def _start_next_action_timer(self):
        self.start_next_action()
        return False

    def complete_sequence(self):
        channel = self.pending_channel
        reason = self.pending_reason
        self.log("{} command complete: {}".format(channel, reason))
        self.pending_channel = None
        self.pending_actions = []
        self.pending_action = None
        self.pending_action_confirmed = False
        self.pending_action_released = False
        self.pending_deadline = None
        self.pending_reason = ""
        self.service["/Scheiber/Pending"] = ""
        if channel:
            self.sync_channel(channel)
        self.write_status(force=True)

    def fail_sequence(self, message):
        channel = self.pending_channel
        if self.release_timer_id is not None:
            try:
                GLib.source_remove(self.release_timer_id)
            except Exception:
                pass
            self.release_timer_id = None
        self.pending_channel = None
        self.pending_actions = []
        self.pending_action = None
        self.pending_action_confirmed = False
        self.pending_action_released = False
        self.pending_deadline = None
        self.pending_reason = ""
        self.service["/Scheiber/Pending"] = ""
        if channel:
            self.sync_channel(channel)
        self.set_error(message, channel)

    def connect_can(self):
        self.can_retry_id = None
        if self.can is not None:
            return False
        s = None
        try:
            s = socket.socket(socket.PF_CAN, socket.SOCK_RAW, socket.CAN_RAW)
            filters = b"".join(
                struct.pack("=II", can_id | CAN_EFF_FLAG, CAN_EFF_MASK | CAN_EFF_FLAG)
                for can_id in relevant_can_ids()
            )
            s.setsockopt(SOL_CAN_RAW, CAN_RAW_FILTER, filters)
            s.setsockopt(SOL_CAN_RAW, CAN_RAW_RECV_OWN_MSGS, 0)
            s.setblocking(False)
            s.bind((CAN_IF,))
            self.can = s
            self.set_connected(1)
            self.can_watch_id = GLib.io_add_watch(
                s.fileno(), GLib.IO_IN | GLib.IO_ERR | GLib.IO_HUP, self.on_can_event
            )
            self.log("SocketCAN connected to {}".format(CAN_IF))
            if TX_ENABLED and QUERY_STATES:
                self.query_index = 0
                self.query_timer_id = GLib.timeout_add(500, self.query_next_state)
            self.write_status(force=True)
            return False
        except Exception as e:
            if s is not None:
                try:
                    s.close()
                except Exception:
                    pass
            self.can = None
            self.set_connected(0)
            self.log("CAN connection failed: {}; retrying in 2s".format(e))
            self.schedule_can_retry()
            return False

    def disconnect_can(self, reason):
        self.log("CAN disconnected: {}".format(reason))
        self.set_connected(0)
        if self.can is not None:
            try:
                self.can.close()
            except Exception:
                pass
        self.can = None
        self.can_watch_id = None
        if self.pending_channel is not None:
            self.fail_sequence("CAN disconnected during pending command: {}".format(reason))
        self.schedule_can_retry()

    def schedule_can_retry(self):
        if self.can_retry_id is None:
            self.can_retry_id = GLib.timeout_add_seconds(2, self.connect_can)

    def send_can_data(self, can_id, data, best_effort=False):
        if self.can is None:
            return False
        frame = struct.pack(
            "=IB3x8s", can_id | CAN_EFF_FLAG, len(data), bytes(data).ljust(8, b"\x00")
        )
        try:
            self.can.send(frame)
            self.log("TX {:08X}#{}".format(can_id, bytes(data).hex().upper()))
            return True
        except OSError as e:
            if not best_effort:
                self.log("CAN TX failed: {}".format(e))
            return False

    def send_rtr(self, can_id):
        if self.can is None:
            return False
        frame = struct.pack(
            "=IB3x8s", can_id | CAN_EFF_FLAG | CAN_RTR_FLAG, 8, b"\x00" * 8
        )
        try:
            self.can.send(frame)
            self.log("TX RTR {:08X}#R8".format(can_id))
            return True
        except OSError as e:
            self.log("CAN RTR TX failed: {}".format(e))
            return False

    def query_next_state(self):
        self.query_timer_id = None
        if self.can is None or not TX_ENABLED or not QUERY_STATES:
            return False
        if self.query_index >= len(STATE_IDS):
            self.state_query_sent = True
            self.service["/Scheiber/StateQuerySent"] = 1
            self.log("Initial RTR state-query batch sent; awaiting/using actual state feedback")
            self.write_status(force=True)
            return False
        can_id = STATE_IDS[self.query_index]
        self.query_index += 1
        self.send_rtr(can_id)
        self.query_timer_id = GLib.timeout_add(30, self.query_next_state)
        return False

    def on_can_event(self, fd, condition):
        if condition & (GLib.IO_ERR | GLib.IO_HUP):
            self.disconnect_can("GLib IO error/hangup")
            return False
        try:
            while True:
                frame = self.can.recv(16)
                if not frame:
                    break
                can_id_raw, dlc, data = struct.unpack("=IB3x8s", frame)
                if can_id_raw & CAN_RTR_FLAG:
                    continue
                can_id = can_id_raw & CAN_EFF_MASK
                payload = data[:dlc]
                if can_id == SWITCH_ID:
                    self.handle_external_switch_event(payload)
                    continue
                changed = self.model.update_frame(can_id, payload)
                if changed:
                    self.sync_all_channels()
                    self.check_pending_confirmation()
                    self.write_status()
        except BlockingIOError:
            pass
        except OSError as e:
            self.disconnect_can(str(e))
            return False
        return True

    def handle_external_switch_event(self, data):
        if len(data) != 5 or not (data[4] & 0x80):
            return
        key = data[4] & 0x7F
        key_name = next((name for name, value in KEYS.items() if value == key), None)
        if key_name is None:
            return
        self.log("RX physical/external panel PRESS {}".format(key_name))
        # A physical press of an automation-capable circuit is a manual override.
        for spec in CHANNELS:
            if spec.supports_automation and spec.key_name == key_name:
                if self.automation_mode[spec.channel_id]:
                    self.automation_mode[spec.channel_id] = False
                    self.service[self.path(spec.channel_id, "Auto")] = 0
                    self.log("{} AUTO cancelled by physical/external panel press".format(spec.name))

    def timer_tick(self):
        if (
            self.pending_action is not None
            and self.pending_deadline is not None
            and time.monotonic() > self.pending_deadline
            and not self.pending_action_confirmed
        ):
            action = self.pending_action
            self.fail_sequence(
                "{} command not confirmed within {:.1f}s; no retry sent".format(
                    action.description, COMMAND_CONFIRM_SECONDS
                )
            )

        self.write_status()
        return True

    def write_status(self, force=False):
        now = time.monotonic()
        if not force and now - self.last_status_snapshot < STATUS_SNAPSHOT_INTERVAL:
            return
        self.last_status_snapshot = now
        channels = {}
        for spec in CHANNELS:
            entry = {
                "synchronized": self.model.channel_synchronized(spec.channel_id),
                "ui_type": spec.ui_type,
            }
            if spec.auto_output is not None:
                entry["mode"] = self.model.bilge_mode(spec.channel_id).value
            else:
                entry["actual_on"] = self.model.channel_binary_state(spec.channel_id)
                if spec.supports_automation:
                    entry["auto"] = self.automation_mode[spec.channel_id]
                    entry["auto_target"] = self.auto_target[spec.channel_id]
            if spec.running_signal is not None:
                entry["running"] = self.model.running_state(spec.channel_id)
            channels[spec.channel_id] = entry

        data = {
            "version": BRIDGE_VERSION,
            "can_interface": CAN_IF,
            "tx_enabled": TX_ENABLED,
            "query_states": QUERY_STATES,
            "state_query_sent": self.state_query_sent,
            "panel_alive_seen": self.model.panel_alive_seen,
            "all_outputs_synchronized": self.model.all_outputs_synchronized(),
            "pending_channel": self.pending_channel,
            "pending_reason": self.pending_reason,
            "last_error": self.last_error,
            "channels": channels,
            "updated": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        }
        try:
            os.makedirs(APP_DIR, exist_ok=True)
            tmp = STATUSFILE + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, sort_keys=True)
                f.write("\n")
            os.replace(tmp, STATUSFILE)
        except Exception as e:
            self.log("WARNING: could not write status snapshot: {}".format(e))


def main():
    bridge = ScheiberSwitchBridge()
    loop = GLib.MainLoop()
    try:
        loop.run()
    except KeyboardInterrupt:
        bridge.log("Stopping on KeyboardInterrupt")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
