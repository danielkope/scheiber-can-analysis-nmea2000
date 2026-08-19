#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Scheiber CAN <-> Victron connected-genset bridge

Version 5.4.2

Design rules:
  * /Start is COMMAND state owned by Victron's generator manager.
    CAN feedback NEVER writes /Start locally.
  * /StatusCode is ACTUAL generator feedback derived from Scheiber CAN.
  * A physical Scheiber START is adopted into Victron by setting the
    generator manager's /ManualStart=1. The manager then writes our /Start=1;
    that write is accepted without retransmitting START on CAN.
  * A physical Scheiber STOP clears /ManualStart only when manual start is
    actually active. Automatic Victron conditions are not silently disabled.
  * No AC-panel commands are sent.
  * No automatic START/STOP retries are sent.
  * SocketCAN kernel filters allow only generator/battery telemetry IDs.
  * Generator telemetry: frequency, gated AC voltage, starter voltage.
  * Battery telemetry: six house-bank IBS channels plus confirmed
    Starboard and Port engine-battery voltage channels (60A charger B1/B3)
    and the generator starter battery (25A charger).
  * House-bank voltage and SoC decodes are confirmed for this installation.
    House-bank current sign/offset are strong; the x0.1 A scale remains a candidate.
  * Engine starter battery voltages (Starboard 12.6V, Port 12.8V) are confirmed
    via the 60A multi-output charger telemetry (0x00501008 / 0x00561008 x 0.1V).
  * Tank telemetry: fresh water, diesel tank 1, diesel tank 2 from
    confirmed Scheiber frame 0x02040580.
  * Startup resynchronization detects a generator that was already running
    when this bridge process starts.
  * Scheiber AC/House applied-source flags are receive-only diagnostics and
    are used to gate generator-voltage publication. No AC-panel CAN commands
    are transmitted.
  * Victron AC-input configuration is NOT rewritten by this bridge. Configure
    AC input 1 = Shore power and AC input 2 = Generator in Venus OS.
  * Generator-manager restart recovery: if dbus-generator/startstop1 disappears
    while the physical genset is starting/running, its replacement manager's
    initialization /Start=0 is suppressed. Manual ownership and any numeric
    ManualStartTimer are restored before normal STOP commands are accepted.
"""

import json
import os
import socket
import struct
import subprocess
import sys
import time
from datetime import datetime
from decimal import Decimal

# ---------------------------------------------------------------------------
# Find Victron velib_python
# ---------------------------------------------------------------------------

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

DBusGMainLoop(set_as_default=True)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

CAN_IF = os.environ.get("CAN_IF", "can2")

SERVICE_NAME = "com.victronenergy.genset.scheiber"
DEVICE_INSTANCE = 40
PRODUCT_ID = 0xFFFF
PRODUCT_NAME = "Scheiber Generator"
BRIDGE_VERSION = "5.8.0"

LOGFILE = "/data/scheiber-gx/bridge.log"
STATUSFILE = "/data/scheiber-gx/status.json"

# Confirmed generator command ID
GEN_CONTROL_ID = 0x02460B88
GEN_START = b"\x01"
GEN_STOP = b"\x02"

# Observed generator state-machine ID
GEN_STATE_ID = 0x02440B88

# Generator-associated frequency ID; bytes 0..1 are uint16 LE x 0.1 Hz
GEN_FREQ_ID = 0x005A1020

# Shared Generator/AC module telemetry; bytes 0..1 BE voltage (V),
# 2..3 BE frequency (Hz).  This is kept as a diagnostic/fallback because it can
# represent another AC source while the generator is off.
GEN_AC_ID = 0x02040898

# Confirmed Scheiber source selector feedback. RECEIVE ONLY.
# byte 0 enum: 0x01 OFF, 0x02 SHORE, 0x04 GENERATOR, 0x08 INVERTER.
AC_PANEL_APPLIED_ID = 0x02400B90
HOUSE_PANEL_APPLIED_ID = 0x02400B88

# Confirmed panel telemetry.
# bytes 4..5 are uint16 BE AC voltage in whole volts.
# bytes 6..7 are frequency/status-like and retained as diagnostics.
AC_PANEL_TELEMETRY_ID = 0x02040B90
HOUSE_PANEL_TELEMETRY_ID = 0x02040B88

# Mastervolt Inverter / AC ramp transition marker (0x02140898)
# byte 0: 0x02 = OFF / Ramp-Down, 0x03 = ON / Ramp-Up
AC_RAMP_MARKER_ID = 0x02140898
AC_RAMP_DOWN = 0x02
AC_RAMP_UP = 0x03

SOURCE_OFF = 0x01
SOURCE_SHORE = 0x02
SOURCE_GENERATOR = 0x04
SOURCE_INVERTER = 0x08

# Generator starter-battery / 0x1020 charger telemetry.
# bytes 0..1: uint16 LE x 0.1 V (strong starter-battery correlation)
# bytes 2..3: uint16 LE x 0.1 A (charger-output-current candidate; diagnostic only)
# bytes 4..5: uint16 LE x 0.1 V (AC input voltage; strong generator-specific
#             candidate because it rises from 0 to ~230 V during generator
#             startup and returns to 0 after shutdown)
GEN_STARTER_ID = 0x00501020

# Six established house-bank IBS-like battery frames.
# bytes 0..1: uint16 LE x 0.01 V  -- CONFIRMED
# bytes 2..3: uint16 LE, offset 0x4E00, x 0.1 A -- CANDIDATE
# bytes 4..5: uint16 LE, x 1 % SoC -- CONFIRMED for this installation
HOUSE_BATTERY_IDS = (
    0x06020580,
    0x06060580,
    0x060A0580,
    0x060E0580,
    0x06120580,
    0x06160580,
)
HOUSE_CURRENT_ZERO = 0x4E00
HOUSE_CURRENT_SCALE = 0.1
HOUSE_VOLTAGE_SCALE = 0.01

# 60A Multi-Output Charger Telemetry (Starboard starter B1, House B2, Port starter B3)
# bytes 0..1: uint16 LE x 0.1 V -> B1: Starboard Engine Starter
CHARGER_60A_TELEMETRY_ID = 0x00501008
# bytes 0..1: uint16 LE x 0.1 V -> B2: House Bank (on 60A charger)
# bytes 2..3: uint16 LE x 0.1 V -> B3: Port Engine Starter
CHARGER_60A_DYNAMIC_ID = 0x00561008
CHARGER_60A_VOLTAGE_SCALE = 0.1

# Confirmed tank-level frame.
#   bytes 0..1: fresh water level, uint16 BE x 1 %
#   bytes 2..3: diesel tank 1 level, uint16 BE x 1 %
#   bytes 4..5: diesel tank 2 level, uint16 BE x 1 %
TANK_LEVEL_ID = 0x02040580

# Victron tank FluidType values:
#   0 = Fuel
#   1 = Fresh water
#
# Vessel capacities are known independently of the CAN mapping and kept here
# in litres for readability. Victron tank D-Bus /Capacity and /Remaining use m3,
# so setup_tank_services() converts litres to cubic metres at publication.
FRESH_WATER_CAPACITY_L = 600.0
DIESEL1_CAPACITY_L = 500.0
DIESEL2_CAPACITY_L = 500.0

TANK_DEFS = (
    # key, service suffix, device instance, custom name, FluidType,
    # word index, optional capacity litres
    (
        "fresh",
        "scheiber_fresh",
        90,
        "Fresh Water",
        1,
        0,
        FRESH_WATER_CAPACITY_L,
    ),
    (
        "diesel1",
        "scheiber_diesel1",
        91,
        "Diesel Tank 1",
        0,
        1,
        DIESEL1_CAPACITY_L,
    ),
    (
        "diesel2",
        "scheiber_diesel2",
        92,
        "Diesel Tank 2",
        0,
        2,
        DIESEL2_CAPACITY_L,
    ),
)

# Stale telemetry handling. House/generator frames are expected frequently;
# engine experimental frames were sparse in the capture, so allow much longer.
FAST_TELEMETRY_STALE_SECONDS = 15.0
ENGINE_TELEMETRY_STALE_SECONDS = 180.0
STATUS_SNAPSHOT_INTERVAL = 5.0

# Victron's automatic system-battery selection may choose any connected
# com.victronenergy.battery service if more than one exists.  To protect the
# existing SmartShunt from being displaced, native per-bank battery services
# are registered only when the GX system battery is explicitly selected.
REQUIRE_EXPLICIT_SYSTEM_BATTERY = True

RUNNING_FREQ_MIN = 47.0
RUNNING_FREQ_MAX = 53.0
STOPPED_FREQ_MAX = 1.0

# Startup resynchronization:
# 005A1020 nominal frequency is authoritative if seen.
# 00501020 charger AC is a secondary fast hint. Require two consecutive
# high-AC samples before using it to recover an already-running generator
# after a bridge restart.
STARTUP_RESYNC_SECONDS = 30.0
STARTUP_CHARGER_AC_MIN = 170.0
STARTUP_CHARGER_AC_MAX = 300.0
STARTUP_CHARGER_AC_CONFIRM_SAMPLES = 2

# 50 Hz was first seen about 9.3 s after START in the controlled capture.
# Once nominal frequency is seen, wait a little longer before declaring RUNNING.
RUNNING_CONFIRM_DELAY = 3.0
START_CONFIRM_TIMEOUT = 35.0

# Normal STOP -> 0 Hz was about 0.9 s.  An aborted start produced a much longer
# transition, so keep this diagnostic timeout generous.  It does NOT trigger a
# retry or any additional CAN command.
STOP_CONFIRM_TIMEOUT = 75.0

# If a physical Scheiber command is adopted by Victron, Victron will shortly
# write the matching value to our /Start path.  Suppress that duplicate CAN TX.
ADOPTION_SUPPRESS_SECONDS = 10.0

# Prevent accidental identical command retransmission from repeated D-Bus writes.
SAME_COMMAND_GUARD = 2.0

# D-Bus generator-manager service prefix created by Victron dbus_generator.
MANAGER_PREFIX = "com.victronenergy.generator.startstop"
BUSITEM_IFACE = "com.victronenergy.BusItem"

# dbus-generator can be restarted by runit. Its newly created startstop service
# initially writes /Start=0. If the physical generator is already running,
# treating that initialization write as a genuine STOP would be unsafe.
MANAGER_CACHE_INTERVAL = 0.5
MANAGER_RECOVERY_SECONDS = 30.0

# Linux SocketCAN constants
CAN_EFF_FLAG = 0x80000000
CAN_EFF_MASK = 0x1FFFFFFF
SOL_CAN_RAW = getattr(socket, "SOL_CAN_RAW", 101)
CAN_RAW_FILTER = getattr(socket, "CAN_RAW_FILTER", 1)
CAN_RAW_RECV_OWN_MSGS = getattr(socket, "CAN_RAW_RECV_OWN_MSGS", 4)

# Connected-genset StatusCode values used by Victron integrations.
STATUS_STOPPED = 0
STATUS_STARTING = 1
STATUS_RUNNING = 8
STATUS_STOPPING = 9

# Native Victron battery services.  Keep the existing SmartShunt selected as
# the system battery; these are intended as additional per-battery telemetry.
BATTERY_DEFS = (
    # key, service suffix, device instance, custom name, CAN ID, mode
    ("house1", "scheiber_house1", 80, "Scheiber House Bank 1", 0x06020580, "house"),
    ("house2", "scheiber_house2", 81, "Scheiber House Bank 2", 0x06060580, "house"),
    ("house3", "scheiber_house3", 82, "Scheiber House Bank 3", 0x060A0580, "house"),
    ("house4", "scheiber_house4", 83, "Scheiber House Bank 4", 0x060E0580, "house"),
    ("house5", "scheiber_house5", 84, "Scheiber House Bank 5", 0x06120580, "house"),
    ("house6", "scheiber_house6", 85, "Scheiber House Bank 6", 0x06160580, "house"),
    ("engine_starboard", "scheiber_engine_starboard", 86, "Starboard Engine Starter Battery", CHARGER_60A_TELEMETRY_ID, "engine_starboard"),
    ("engine_port", "scheiber_engine_port", 87, "Port Engine Starter Battery", CHARGER_60A_DYNAMIC_ID, "engine_port"),
    ("generator", "scheiber_generator_starter", 88, "Generator Starter Battery", GEN_STARTER_ID, "generator"),
)
BATTERY_KEY_BY_CAN = {row[4]: row[0] for row in BATTERY_DEFS}
HOUSE_KEY_BY_CAN = {
    row[4]: row[0] for row in BATTERY_DEFS if row[5] == "house"
}
CAN_FILTER_IDS = tuple(sorted(set(
    (
        GEN_CONTROL_ID,
        GEN_STATE_ID,
        GEN_FREQ_ID,
        GEN_AC_ID,
        GEN_STARTER_ID,
        TANK_LEVEL_ID,
        AC_PANEL_APPLIED_ID,
        HOUSE_PANEL_APPLIED_ID,
        AC_PANEL_TELEMETRY_ID,
        HOUSE_PANEL_TELEMETRY_ID,
        AC_RAMP_MARKER_ID,
        CHARGER_60A_TELEMETRY_ID,
        CHARGER_60A_DYNAMIC_ID,
    )
    + HOUSE_BATTERY_IDS
)))
_UNSET = object()


class Bridge:
    def __init__(self):
        self.bus = dbus.SystemBus()

        self.can = None
        self.can_watch_id = None
        self.can_retry_id = None

        self.service = None

        # Victron generator-manager service controlling this genset.
        self.manager_service = None
        self.manager_discovery_id = None
        self.queued_manual_value = None
        self.external_manual_adopted = False

        # Cache the live Victron manager state so it survives a manager-process
        # restart. In particular, ManualStartTimer is in-memory state inside
        # dbus-generator and otherwise disappears when that process restarts.
        self.manager_cache_next = 0.0
        self.cached_manager_manual_start = None
        self.cached_manager_manual_timer = None
        self.cached_manager_running_by_code = None
        self.cached_manager_running_by = None
        self.cached_manager_state = None
        self.cached_manager_updated = None

        # Recovery guard. It is entered only when a generator manager
        # disappears while the physical generator is STARTING/RUNNING, or an
        # external/startup running condition is detected before a manager is
        # available.
        self.manager_recovery_active = False
        self.manager_recovery_until = 0.0
        self.manager_recovery_reason = None
        self.manager_recovery_restore_manual = False
        self.manager_recovery_timer = 0
        self.manager_recovery_running_by_code = None

        # When an external CAN command is adopted into /ManualStart, the
        # generator manager will write the same state to our /Start path.
        # That write is command synchronization, not a request for another
        # physical CAN command.
        self.expected_start_write = None
        self.expected_start_write_until = 0.0

        # Physical generator state.
        self.actual_state = "UNKNOWN"
        self.state_reason = "bridge startup"
        self.last_state_code = None
        self.last_frequency = None
        self.last_ac_module_voltage = None
        self.last_ac_module_frequency = None
        self.last_starter_voltage = None
        self.last_generator_charger_current = None
        self.last_generator_charger_ac_voltage = None
        self.gen_ac_last_update = None
        self.gen_starter_last_update = None
        self.gen_charger_ac_last_update = None

        # Scheiber source-selection and panel telemetry.
        self.ac_panel_applied_source = None
        self.house_panel_applied_source = None
        self.mastervolt_inverter_state = 0
        self.last_ac_panel_voltage = None
        self.last_house_panel_voltage = None
        self.last_ac_panel_freq_status = None
        self.last_house_panel_freq_status = None
        self.ac_panel_last_update = None
        self.house_panel_last_update = None

        # Startup resynchronization for bridge restarts while genset is running.
        self.startup_resync_active = True
        self.startup_resync_started = time.monotonic()
        self.startup_charger_ac_samples = 0
        self.startup_running_adoption_pending = False

        self.last_status_snapshot = time.monotonic()

        # Additional Victron battery services and freshness timestamps.
        self.battery_services = {}
        self.battery_last_update = {}
        # Each exported Victron service needs its own private D-Bus connection.
        # D-Bus object paths are connection-scoped; reusing one connection for
        # multiple VeDbusService instances that all export "/" and "/Mgmt/..."
        # causes an immediate registration collision.
        self.battery_buses = {}

        # Native Victron tank services. Each gets its own private D-Bus
        # connection for the same reason as the per-battery services.
        self.tank_services = {}
        self.tank_buses = {}
        self.tank_last_update = {}

        # Native Victron Grid/Shore power service (receive-only).
        self.shore_service = None
        self.shore_bus = None

        # Native Victron Inverter service for MasterVolt 2000W.
        self.mastervolt_service = None
        self.mastervolt_bus = None

        # Transition tracking.  Diagnostic only: timeouts never retry commands.
        self.running_candidate_since = None
        self.pending = None
        self.pending_since = None
        self.pending_origin = None

        # Command de-duplication.
        self.last_tx_command = None
        self.last_tx_time = 0.0

        self.log("================================================")
        self.log("Scheiber connected-genset bridge V{}".format(BRIDGE_VERSION))
        self.log("D-Bus service : {}".format(SERVICE_NAME))
        self.log("CAN interface : {}".format(CAN_IF))
        self.log("START         : 02460B88#01")
        self.log("STOP          : 02460B88#02")
        self.log("AC control    : DISABLED")
        self.log("Auto retries  : DISABLED")
        self.log("================================================")

        self.setup_dbus()
        self.setup_grid_service()
        self.setup_mastervolt_inverter_service()
        self.setup_battery_services()
        self.setup_tank_services()
        self.setup_name_owner_watch()
        self.log_victron_ac_configuration()
        self.schedule_manager_discovery(immediate=True)
        self.connect_can()

        GLib.timeout_add(100, self.timer_tick)
        self.write_status()

    # ------------------------------------------------------------------
    # Logging/status
    # ------------------------------------------------------------------

    def log(self, msg):
        line = "{} {}\n".format(
            datetime.now().strftime("%Y-%m-%d %H:%M:%S"), msg
        )
        print(line, end="", flush=True)
        try:
            with open(LOGFILE, "a") as f:
                f.write(line)
        except Exception:
            pass

    def write_status(self):
        try:
            command_start = self.service["/Start"] if self.service else None
            status_code = self.service["/StatusCode"] if self.service else None
            connected = self.service["/Connected"] if self.service else 0
        except Exception:
            command_start = None
            status_code = None
            connected = 0

        batteries = {}
        for key, svc in self.battery_services.items():
            try:
                batteries[key] = {
                    "name": str(svc["/CustomName"]),
                    "voltage_v": svc["/Dc/0/Voltage"],
                    "current_a": svc["/Dc/0/Current"],
                    "soc_percent": svc["/Soc"],
                    "power_w": svc["/Dc/0/Power"],
                    "can_id": svc["/Scheiber/CanId"],
                    "decode": str(svc["/Scheiber/Decode"]),
                    "last_update_monotonic": self.battery_last_update.get(key),
                }
            except Exception:
                pass

        tanks = {}
        for key, svc in self.tank_services.items():
            try:
                tanks[key] = {
                    "name": str(svc["/CustomName"]),
                    "level_percent": svc["/Level"],
                    "fluid_type": svc["/FluidType"],
                    "capacity_m3": svc["/Capacity"],
                    "remaining_m3": svc["/Remaining"],
                    "raw_value": svc["/Scheiber/RawValue"],
                    "last_update_monotonic": self.tank_last_update.get(key),
                }
            except Exception:
                pass

        data = {
            "actual_state": self.actual_state,
            "state_reason": self.state_reason,
            "victron_command_start": command_start,
            "status_code": status_code,
            "connected": connected,
            "last_frequency_hz": self.last_frequency,
            "last_ac_module_voltage_v": self.last_ac_module_voltage,
            "last_ac_module_frequency_hz": self.last_ac_module_frequency,
            "last_starter_voltage_v": self.last_starter_voltage,
            "last_generator_charger_current_a": self.last_generator_charger_current,
            "last_generator_charger_ac_voltage_v": self.last_generator_charger_ac_voltage,
            "ac_panel_applied_source": self.ac_panel_applied_source,
            "ac_panel_applied_source_text": (
                self.service["/Scheiber/AcPanelAppliedSourceText"]
                if self.service
                else None
            ),
            "house_panel_applied_source": (
                self.service["/Scheiber/HousePanelAppliedSource"]
                if self.service
                else None
            ),
            "house_panel_applied_source_text": (
                self.service["/Scheiber/HousePanelAppliedSourceText"]
                if self.service
                else None
            ),
            "mastervolt_inverter_state": self.mastervolt_inverter_state,
            "mastervolt_inverter_state_text": (
                "ON" if self.mastervolt_inverter_state == 1 else "OFF"
            ),
            "ac_panel_voltage_v": self.last_ac_panel_voltage,
            "house_panel_voltage_v": self.last_house_panel_voltage,
            "startup_resync_active": self.startup_resync_active,
            "startup_charger_ac_samples": self.startup_charger_ac_samples,
            "last_scheiber_state_code": self.last_state_code,
            "pending": self.pending,
            "pending_origin": self.pending_origin,
            "manager_service": self.manager_service,
            "external_manual_adopted": self.external_manual_adopted,
            "manager_cache": {
                "manual_start": self.cached_manager_manual_start,
                "manual_start_timer": self.cached_manager_manual_timer,
                "running_by_code": self.cached_manager_running_by_code,
                "running_by": self.cached_manager_running_by,
                "state": self.cached_manager_state,
                "updated_monotonic": self.cached_manager_updated,
            },
            "manager_recovery": {
                "active": self.manager_recovery_active,
                "reason": self.manager_recovery_reason,
                "restore_manual": self.manager_recovery_restore_manual,
                "timer": self.manager_recovery_timer,
                "running_by_code": self.manager_recovery_running_by_code,
            },
            "batteries": batteries,
            "tanks": tanks,
            "updated": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        }

        tmp = STATUSFILE + ".tmp"
        try:
            with open(tmp, "w") as f:
                json.dump(data, f, indent=2, sort_keys=True)
                f.write("\n")
            os.replace(tmp, STATUSFILE)
        except Exception as e:
            self.log("WARNING: could not write status.json: {}".format(e))

    # ------------------------------------------------------------------
    # Victron D-Bus service
    # ------------------------------------------------------------------

    def setup_dbus(self):
        self.service = VeDbusService(SERVICE_NAME, register=False)
        self.service.add_mandatory_paths(
            processname=os.path.abspath(__file__),
            processversion=BRIDGE_VERSION,
            connection="Scheiber CAN on {}".format(CAN_IF),
            deviceinstance=DEVICE_INSTANCE,
            productid=PRODUCT_ID,
            productname=PRODUCT_NAME,
            firmwareversion=BRIDGE_VERSION,
            hardwareversion=None,
            connected=0,
        )

        self.service.add_path("/CustomName", PRODUCT_NAME)
        self.service.add_path("/Serial", "scheiber-can-{}".format(CAN_IF))
        self.service.add_path("/Model", "Scheiber CAN bridge")
        self.service.add_path("/Role", "genset")
        self.service.add_path("/NrOfPhases", 1)

        # Required by Victron's connected-genset driver.
        self.service.add_path("/RemoteStartModeEnabled", 1)

        # IMPORTANT: /Start is COMMAND state.  It is changed only by an
        # external D-Bus SetValue (normally Victron dbus_generator).
        # Physical CAN feedback must never locally assign this path.
        self.service.add_path(
            "/Start",
            0,
            writeable=True,
            onchangecallback=self.on_start_write,
        )

        # Initialize StatusCode to a valid numeric value so dbus_generator
        # recognizes this genset as providing feedback from the moment it is
        # discovered.  CAN observations will immediately replace it as needed.
        self.service.add_path("/StatusCode", STATUS_STOPPED)

        # Victron genset integrations commonly expose /Ac/Frequency.  Keep
        # /Ac/L1/Frequency too for compatibility with existing V5.1 consumers.
        self.service.add_path(
            "/Ac/Frequency",
            None,
            gettextcallback=lambda p, v: (
                "---" if v is None else "{:.1f} Hz".format(float(v))
            ),
        )
        self.service.add_path(
            "/Ac/L1/Frequency",
            None,
            gettextcallback=lambda p, v: (
                "---" if v is None else "{:.1f} Hz".format(float(v))
            ),
        )
        self.service.add_path(
            "/Ac/L1/Voltage",
            None,
            gettextcallback=lambda p, v: (
                "---" if v is None else "{:.0f} V".format(float(v))
            ),
        )
        self.service.add_path(
            "/StarterVoltage",
            None,
            gettextcallback=lambda p, v: (
                "---" if v is None else "{:.1f} V".format(float(v))
            ),
        )

        # Diagnostic paths.  They are ignored by normal Victron generator code.
        self.service.add_path("/Scheiber/State", self.actual_state)
        self.service.add_path("/Scheiber/StateCode", None)
        self.service.add_path("/Scheiber/StateReason", self.state_reason)
        self.service.add_path("/Scheiber/AcModuleVoltage", None)
        self.service.add_path("/Scheiber/AcModuleFrequency", None)
        self.service.add_path("/Scheiber/GeneratorChargerCurrent", None)
        self.service.add_path("/Scheiber/GeneratorChargerAcVoltage", None)
        self.service.add_path("/Scheiber/AcPanelAppliedSource", None)
        self.service.add_path("/Scheiber/AcPanelAppliedSourceText", None)
        self.service.add_path("/Scheiber/HousePanelAppliedSource", None)
        self.service.add_path("/Scheiber/HousePanelAppliedSourceText", None)
        self.service.add_path("/Scheiber/MastervoltInverterState", 0)
        self.service.add_path("/Scheiber/MastervoltInverterStateText", "OFF")
        self.service.add_path("/Scheiber/AcPanelVoltage", None)
        self.service.add_path("/Scheiber/HousePanelVoltage", None)
        self.service.add_path("/Scheiber/AcPanelFrequencyStatus", None)
        self.service.add_path("/Scheiber/HousePanelFrequencyStatus", None)
        self.service.add_path("/Scheiber/StartupResyncActive", 1)

        self.service.register()
        self.log("Registered {}".format(SERVICE_NAME))

    def setup_grid_service(self):
        """Create native Victron grid/shore power telemetry service (receive-only)."""
        service_name = "com.victronenergy.grid.scheiber_shore"
        self.shore_bus = dbus.Bus.get_system(private=True)
        svc = VeDbusService(
            service_name,
            bus=self.shore_bus,
            register=False,
        )
        svc.add_mandatory_paths(
            processname=os.path.abspath(__file__),
            processversion=BRIDGE_VERSION,
            connection="Scheiber CAN on {}".format(CAN_IF),
            deviceinstance=41,
            productid=PRODUCT_ID,
            productname="Scheiber Shore Power",
            firmwareversion=BRIDGE_VERSION,
            hardwareversion=None,
            connected=0,
        )
        svc.add_path("/CustomName", "Shore Power")
        svc.add_path("/Ac/NumberOfPhases", 1)
        svc.add_path(
            "/Ac/L1/Voltage",
            None,
            gettextcallback=lambda p, v: (
                "---" if v is None else "{:.1f} V".format(float(v))
            ),
        )
        svc.add_path(
            "/Ac/L1/Current",
            None,
            gettextcallback=lambda p, v: (
                "---" if v is None else "{:.1f} A".format(float(v))
            ),
        )
        svc.add_path(
            "/Ac/L1/Power",
            None,
            gettextcallback=lambda p, v: (
                "---" if v is None else "{:.0f} W".format(float(v))
            ),
        )
        svc.add_path("/Ac/L1/Energy/Forward", None)
        svc.add_path("/Ac/L1/Energy/Reverse", None)
        svc.register()
        self.shore_service = svc
        self.log("Registered {}".format(service_name))

    def setup_mastervolt_inverter_service(self):
        """Create native Victron inverter telemetry service for MasterVolt 2000W."""
        service_name = "com.victronenergy.inverter.scheiber_mastervolt"
        self.mastervolt_bus = dbus.Bus.get_system(private=True)
        svc = VeDbusService(
            service_name,
            bus=self.mastervolt_bus,
            register=False,
        )
        svc.add_mandatory_paths(
            processname=os.path.abspath(__file__),
            processversion=BRIDGE_VERSION,
            connection="Scheiber CAN on {}".format(CAN_IF),
            deviceinstance=270,
            productid=PRODUCT_ID,
            productname="MasterVolt 2000W Inverter",
            firmwareversion=BRIDGE_VERSION,
            hardwareversion=None,
            connected=1,
        )
        svc.add_path("/CustomName", "MasterVolt 2000W")
        svc.add_path("/State", 0)
        svc.add_path("/Mode", 4)
        svc.add_path(
            "/Ac/Out/L1/V",
            None,
            gettextcallback=lambda p, v: (
                "---" if v is None else "{:.1f} V".format(float(v))
            ),
        )
        svc.add_path(
            "/Ac/Out/L1/P",
            None,
            gettextcallback=lambda p, v: (
                "---" if v is None else "{:.0f} W".format(float(v))
            ),
        )
        svc.add_path(
            "/Ac/Out/L1/I",
            None,
            gettextcallback=lambda p, v: (
                "---" if v is None else "{:.1f} A".format(float(v))
            ),
        )
        svc.add_path(
            "/Dc/0/Voltage",
            None,
            gettextcallback=lambda p, v: (
                "---" if v is None else "{:.2f} V".format(float(v))
            ),
        )
        svc.add_path("/Alarms/LowVoltage", 0)
        svc.add_path("/Alarms/HighVoltage", 0)
        svc.add_path("/Alarms/Overload", 0)
        svc.add_path("/Alarms/HighTemperature", 0)
        svc.register()
        self.mastervolt_service = svc
        self.log("Registered {}".format(service_name))

    def setup_battery_services(self):
        """Create native Victron battery telemetry services.

        House-bank voltage and SoC are confirmed for this installation.
        House-bank current sign/offset are strong; the x0.1 A scale remains
        a candidate and is intentionally kept easy to change.

        Engine Battery A/B source IDs and voltage scale are explicitly
        experimental. The raw word and scale are also exported so the mapping
        can be validated without losing the original data.
        """
        if REQUIRE_EXPLICIT_SYSTEM_BATTERY:
            try:
                selected = str(
                    self.dbus_get(
                        "com.victronenergy.settings",
                        "/Settings/SystemSetup/BatteryService",
                    )
                )
            except Exception as e:
                self.log(
                    "SAFETY: could not read GX system battery selection ({}); "
                    "native Scheiber battery services will NOT be registered"
                    .format(e)
                )
                return

            if selected in ("default", "None", ""):
                self.log(
                    "SAFETY: GX system battery is not explicitly selected "
                    "(value={!r}). Native Scheiber battery services are NOT "
                    "registered to avoid displacing the SmartShunt. Select "
                    "the SmartShunt explicitly, then restart this bridge."
                    .format(selected)
                )
                return

            self.log(
                "GX system battery selection is explicit: {}; enabling "
                "Scheiber per-battery services".format(selected)
            )

        for key, suffix, instance, custom_name, can_id, mode in BATTERY_DEFS:
            service_name = "com.victronenergy.battery.{}".format(suffix)

            # IMPORTANT: use a separate private D-Bus connection per exported
            # battery service. VeDbusService exports identical object paths
            # (/, /Mgmt/..., /Dc/0/...) for every service. Those paths are
            # connection-scoped in dbus-python, so sharing the process-wide
            # SystemBus connection makes the second service collide and crash.
            battery_bus = dbus.Bus.get_system(private=True)
            svc = VeDbusService(
                service_name,
                bus=battery_bus,
                register=False,
            )
            svc.add_mandatory_paths(
                processname=os.path.abspath(__file__),
                processversion=BRIDGE_VERSION,
                connection="Scheiber CAN on {}".format(CAN_IF),
                deviceinstance=instance,
                productid=PRODUCT_ID,
                productname=custom_name,
                firmwareversion=BRIDGE_VERSION,
                hardwareversion=None,
                connected=0,
            )
            svc.add_path("/CustomName", custom_name)
            svc.add_path("/Serial", "{}-{:08X}".format(suffix, can_id))
            svc.add_path(
                "/Dc/0/Voltage",
                None,
                gettextcallback=lambda p, v: (
                    "---" if v is None else "{:.2f} V".format(float(v))
                ),
            )
            svc.add_path(
                "/Dc/0/Current",
                None,
                gettextcallback=lambda p, v: (
                    "---" if v is None else "{:.1f} A".format(float(v))
                ),
            )
            svc.add_path(
                "/Dc/0/Power",
                None,
                gettextcallback=lambda p, v: (
                    "---" if v is None else "{:.0f} W".format(float(v))
                ),
            )
            svc.add_path(
                "/Soc",
                None,
                gettextcallback=lambda p, v: (
                    "---" if v is None else "{:.0f}%".format(float(v))
                ),
            )

            # Transparent diagnostic metadata.
            svc.add_path("/Scheiber/CanId", "{:08X}".format(can_id))
            svc.add_path("/Scheiber/Mode", mode)
            if mode == "house":
                decode = (
                    "V=LE16*0.01 confirmed; "
                    "I=(LE16-0x4E00)*0.1 candidate; "
                    "SoC=LE16% confirmed"
                )
            elif mode == "engine_starboard":
                decode = "V=LE16[0..1]*0.1 confirmed (60A charger B1 Starboard starter)"
            elif mode == "engine_port":
                decode = "V=LE16[2..3]*0.1 confirmed (60A charger B3 Port starter)"
            else:
                decode = "V=LE16*0.1 generator-starter correlation"

            svc.add_path("/Scheiber/Decode", decode)
            svc.add_path("/Scheiber/RawWord0", None)
            svc.add_path("/Scheiber/RawWord1", None)
            svc.add_path("/Scheiber/RawWord2", None)

            svc.register()
            # Keep both the service and its private connection alive explicitly.
            self.battery_buses[key] = battery_bus
            self.battery_services[key] = svc
            self.battery_last_update[key] = None
            self.log(
                "Registered battery telemetry {} ({}, CAN {:08X})".format(
                    service_name, custom_name, can_id
                )
            )

    def setup_tank_services(self):
        """Create native Victron tank services for the confirmed Scheiber levels.

        The source frame is 0x02040580:
          word 0 BE = fresh water %
          word 1 BE = diesel tank 1 %
          word 2 BE = diesel tank 2 %

        Tank telemetry is sample-and-hold: the last valid percentage remains
        published until a newer valid CAN sample arrives.
        """
        for (
            key,
            suffix,
            instance,
            custom_name,
            fluid_type,
            word_index,
            capacity_l,
        ) in TANK_DEFS:
            service_name = "com.victronenergy.tank.{}".format(suffix)

            # Each VeDbusService gets a private connection because all services
            # export common object paths such as "/" and "/Mgmt/...".
            tank_bus = dbus.Bus.get_system(private=True)
            svc = VeDbusService(
                service_name,
                bus=tank_bus,
                register=False,
            )
            svc.add_mandatory_paths(
                processname=os.path.abspath(__file__),
                processversion=BRIDGE_VERSION,
                connection="Scheiber CAN on {}".format(CAN_IF),
                deviceinstance=instance,
                productid=PRODUCT_ID,
                productname="Scheiber Tank Sensor",
                firmwareversion=BRIDGE_VERSION,
                hardwareversion=None,
                connected=0,
            )

            svc.add_path("/CustomName", custom_name)
            svc.add_path("/FluidType", int(fluid_type))
            svc.add_path(
                "/Level",
                None,
                gettextcallback=lambda p, v: (
                    "---" if v is None else "{:.0f} %".format(float(v))
                ),
            )
            svc.add_path("/Status", 0)

            # Capacity/Remaining are optional. The configuration is in litres,
            # while Victron D-Bus stores tank volumes in cubic metres.
            svc.add_path(
                "/Capacity",
                None if capacity_l is None else float(capacity_l) / 1000.0,
                gettextcallback=lambda p, v: (
                    "---" if v is None else "{:.1f} L".format(float(v) * 1000.0)
                ),
            )
            svc.add_path(
                "/Remaining",
                None,
                gettextcallback=lambda p, v: (
                    "---" if v is None else "{:.1f} L".format(float(v) * 1000.0)
                ),
            )

            # Diagnostics.
            svc.add_path("/Scheiber/CanId", int(TANK_LEVEL_ID))
            svc.add_path("/Scheiber/WordIndex", int(word_index))
            svc.add_path("/Scheiber/RawValue", None)
            svc.add_path("/Scheiber/Decode", "uint16 BE x 1 % confirmed")

            svc.register()
            self.tank_buses[key] = tank_bus
            self.tank_services[key] = svc
            self.tank_last_update[key] = None

            self.log(
                "Registered tank telemetry {} ({}, FluidType {}, "
                "0x{:08X} word {})".format(
                    service_name,
                    custom_name,
                    fluid_type,
                    TANK_LEVEL_ID,
                    word_index,
                )
            )

    def update_tank_service(self, key, raw_level):
        svc = self.tank_services.get(key)
        if svc is None:
            return

        raw_level = int(raw_level)
        svc["/Scheiber/RawValue"] = raw_level

        # Keep the previous good sample if an invalid/sentinel value arrives.
        if not 0 <= raw_level <= 100:
            return

        level = float(raw_level)
        svc["/Level"] = level

        capacity = svc["/Capacity"]
        if capacity is not None:
            svc["/Remaining"] = round(float(capacity) * level / 100.0, 3)
        else:
            svc["/Remaining"] = None

        svc["/Status"] = 0
        self.tank_last_update[key] = time.monotonic()

    def set_all_connected(self, value):
        value = int(bool(value))
        self.service["/Connected"] = value
        for svc in self.battery_services.values():
            svc["/Connected"] = value
        for svc in self.tank_services.values():
            svc["/Connected"] = value
        if value == 0 and self.shore_service:
            self.shore_service["/Connected"] = 0

    def update_battery_service(
        self,
        key,
        voltage=_UNSET,
        current=_UNSET,
        soc=_UNSET,
        raw_words=None,
    ):
        svc = self.battery_services.get(key)
        if svc is None:
            return

        if voltage is not _UNSET:
            svc["/Dc/0/Voltage"] = (
                None if voltage is None else float(voltage)
            )
        if current is not _UNSET:
            svc["/Dc/0/Current"] = (
                None if current is None else float(current)
            )
        if soc is not _UNSET:
            svc["/Soc"] = None if soc is None else float(soc)

        v = svc["/Dc/0/Voltage"]
        i = svc["/Dc/0/Current"]
        svc["/Dc/0/Power"] = (
            round(float(v) * float(i), 1)
            if v is not None and i is not None
            else None
        )

        if raw_words is not None:
            for idx, raw in enumerate(raw_words[:3]):
                svc["/Scheiber/RawWord{}".format(idx)] = int(raw)

        self.battery_last_update[key] = time.monotonic()

    def invalidate_battery_service(self, key):
        svc = self.battery_services.get(key)
        if svc is None:
            return
        svc["/Dc/0/Voltage"] = None
        svc["/Dc/0/Current"] = None
        svc["/Dc/0/Power"] = None
        svc["/Soc"] = None

    def update_ac_sources(self):
        """Update applied AC source telemetry and Mastervolt inverter state."""
        now = time.monotonic()
        has_voltage = (
            self.last_house_panel_voltage is not None
            and self.house_panel_last_update is not None
            and now - self.house_panel_last_update <= FAST_TELEMETRY_STALE_SECONDS
            and 80.0 <= float(self.last_house_panel_voltage) <= 300.0
        )
        is_inverting = (
            self.mastervolt_inverter_state == 1
            or (has_voltage and self.house_panel_applied_source in (SOURCE_OFF, None, 0x01))
        )

        ac_name = {
            SOURCE_OFF: "OFF",
            SOURCE_SHORE: "SHORE",
            SOURCE_GENERATOR: "GENERATOR",
        }.get(
            self.ac_panel_applied_source,
            "UNKNOWN" if self.ac_panel_applied_source is not None else None,
        )

        if (
            is_inverting
            and self.house_panel_applied_source in (SOURCE_OFF, None, 0x01)
        ):
            house_source_effective = SOURCE_INVERTER
            house_name = "INVERTER"
        else:
            house_source_effective = self.house_panel_applied_source
            house_name = {
                SOURCE_OFF: "OFF",
                SOURCE_SHORE: "SHORE",
                SOURCE_GENERATOR: "GENERATOR",
                SOURCE_INVERTER: "INVERTER",
            }.get(
                self.house_panel_applied_source,
                "UNKNOWN" if self.house_panel_applied_source is not None else None,
            )

        if self.service:
            self.service["/Scheiber/AcPanelAppliedSource"] = self.ac_panel_applied_source
            self.service["/Scheiber/AcPanelAppliedSourceText"] = ac_name
            self.service["/Scheiber/HousePanelAppliedSource"] = house_source_effective
            self.service["/Scheiber/HousePanelAppliedSourceText"] = house_name
            self.service["/Scheiber/MastervoltInverterState"] = 1 if is_inverting else 0
            self.service["/Scheiber/MastervoltInverterStateText"] = (
                "ON" if is_inverting else "OFF"
            )

    def update_genset_ac_voltage_publication(self):
        """Publish generator voltage only when the source evidence fits."""
        now = time.monotonic()
        active = self.actual_state in (
            "STARTING",
            "RUNNING",
            "RUNNING_SETTLED",
            "STOPPING",
        )

        if not active:
            self.service["/Ac/L1/Voltage"] = None
            return

        # Preferred: panel voltage explicitly applied to GENERATOR.
        if (
            self.ac_panel_applied_source == SOURCE_GENERATOR
            and self.last_ac_panel_voltage is not None
            and self.ac_panel_last_update is not None
            and now - self.ac_panel_last_update <= FAST_TELEMETRY_STALE_SECONDS
            and 80.0 <= float(self.last_ac_panel_voltage) <= 300.0
        ):
            self.service["/Ac/L1/Voltage"] = float(self.last_ac_panel_voltage)
            return

        if (
            self.house_panel_applied_source == SOURCE_GENERATOR
            and self.last_house_panel_voltage is not None
            and self.house_panel_last_update is not None
            and now - self.house_panel_last_update <= FAST_TELEMETRY_STALE_SECONDS
            and 80.0 <= float(self.last_house_panel_voltage) <= 300.0
        ):
            self.service["/Ac/L1/Voltage"] = float(self.last_house_panel_voltage)
            return

        # Restart fallback: shared AC module is accepted only after RUNNING is
        # independently established and its own frequency is nominal.
        if (
            self.actual_state in ("RUNNING", "RUNNING_SETTLED")
            and self.last_ac_module_voltage is not None
            and self.last_ac_module_frequency is not None
            and self.gen_ac_last_update is not None
            and now - self.gen_ac_last_update <= FAST_TELEMETRY_STALE_SECONDS
            and 80.0 <= float(self.last_ac_module_voltage) <= 300.0
            and RUNNING_FREQ_MIN
            <= float(self.last_ac_module_frequency)
            <= RUNNING_FREQ_MAX
        ):
            self.service["/Ac/L1/Voltage"] = float(self.last_ac_module_voltage)
            return

        self.service["/Ac/L1/Voltage"] = None

    def update_shore_power_publication(self):
        """Publish shore power telemetry only when Scheiber feedback confirms SHORE is applied."""
        if not self.shore_service:
            return

        now = time.monotonic()
        shore_applied = (
            self.house_panel_applied_source == SOURCE_SHORE
            or self.ac_panel_applied_source == SOURCE_SHORE
        )

        voltage = None
        if (
            self.house_panel_applied_source == SOURCE_SHORE
            and self.last_house_panel_voltage is not None
            and self.house_panel_last_update is not None
            and now - self.house_panel_last_update <= FAST_TELEMETRY_STALE_SECONDS
            and 80.0 <= float(self.last_house_panel_voltage) <= 300.0
        ):
            voltage = float(self.last_house_panel_voltage)
        elif (
            self.ac_panel_applied_source == SOURCE_SHORE
            and self.last_ac_panel_voltage is not None
            and self.ac_panel_last_update is not None
            and now - self.ac_panel_last_update <= FAST_TELEMETRY_STALE_SECONDS
            and 80.0 <= float(self.last_ac_panel_voltage) <= 300.0
        ):
            voltage = float(self.last_ac_panel_voltage)

        if shore_applied and voltage is not None:
            self.shore_service["/Connected"] = 1
            self.shore_service["/Ac/L1/Voltage"] = voltage
        else:
            self.shore_service["/Connected"] = 0
            self.shore_service["/Ac/L1/Voltage"] = None
            self.shore_service["/Ac/L1/Power"] = None
            self.shore_service["/Ac/L1/Current"] = None

    def update_mastervolt_inverter_publication(self):
        """Update native MasterVolt 2000W inverter telemetry service."""
        if not self.mastervolt_service:
            return

        now = time.monotonic()
        has_voltage = (
            self.last_house_panel_voltage is not None
            and self.house_panel_last_update is not None
            and now - self.house_panel_last_update <= FAST_TELEMETRY_STALE_SECONDS
            and 80.0 <= float(self.last_house_panel_voltage) <= 300.0
        )
        not_grid_or_gen = self.house_panel_applied_source in (SOURCE_OFF, None, 0x01)

        is_inverting = (self.mastervolt_inverter_state == 1) or (has_voltage and not_grid_or_gen)

        self.mastervolt_service["/State"] = 9 if is_inverting else 0
        self.mastervolt_service["/Mode"] = 2 if is_inverting else 4

        if is_inverting and has_voltage:
            self.mastervolt_service["/Ac/Out/L1/V"] = float(self.last_house_panel_voltage)
        else:
            self.mastervolt_service["/Ac/Out/L1/V"] = None

        house_bat = self.battery_services.get("house_combined")
        if house_bat and house_bat["/Dc/0/Voltage"] is not None:
            self.mastervolt_service["/Dc/0/Voltage"] = house_bat["/Dc/0/Voltage"]


    # ------------------------------------------------------------------
    # Victron generator-manager discovery/adoption
    # ------------------------------------------------------------------

    def setup_name_owner_watch(self):
        self.bus.add_signal_receiver(
            self.on_name_owner_changed,
            signal_name="NameOwnerChanged",
            dbus_interface="org.freedesktop.DBus",
            bus_name="org.freedesktop.DBus",
            path="/org/freedesktop/DBus",
        )

    @staticmethod
    def victron_ac_input_name(value):
        try:
            value = int(value)
        except Exception:
            return "unknown"
        return {
            0: "Not available",
            1: "Grid",
            2: "Generator",
            3: "Shore power",
        }.get(value, "Unknown({})".format(value))

    def log_victron_ac_configuration(self):
        try:
            ac1 = self.dbus_get(
                "com.victronenergy.settings",
                "/Settings/SystemSetup/AcInput1",
            )
            ac2 = self.dbus_get(
                "com.victronenergy.settings",
                "/Settings/SystemSetup/AcInput2",
            )
            self.log(
                "Victron AC configuration (read-only): Input1={} ({}), "
                "Input2={} ({})".format(
                    int(ac1),
                    self.victron_ac_input_name(ac1),
                    int(ac2),
                    self.victron_ac_input_name(ac2),
                )
            )
            if int(ac1) != 3 or int(ac2) != 2:
                self.log(
                    "NOTE: expected vessel configuration is AC input 1 = Shore "
                    "power (3), AC input 2 = Generator (2); the bridge does not "
                    "change these settings"
                )
        except Exception as e:
            self.log("Could not read Victron AC input configuration: {}".format(e))

    def refresh_manager_cache(self, force=False):
        """Snapshot generator-manager state without changing anything."""
        if self.manager_service is None:
            return False

        now = time.monotonic()
        if not force and now < self.manager_cache_next:
            return True
        self.manager_cache_next = now + MANAGER_CACHE_INTERVAL

        try:
            manual = int(self.dbus_get(self.manager_service, "/ManualStart"))
            timer = int(self.dbus_get(self.manager_service, "/ManualStartTimer"))
            running_code = int(
                self.dbus_get(self.manager_service, "/RunningByConditionCode")
            )
            running_by = str(
                self.dbus_get(self.manager_service, "/RunningByCondition")
            )
            state = int(self.dbus_get(self.manager_service, "/State"))
        except Exception:
            # Keep the last good snapshot. A disappearing manager can race this
            # read; overwriting the cache with guessed zeros would defeat
            # recovery.
            return False

        self.cached_manager_manual_start = manual
        self.cached_manager_manual_timer = max(0, timer)
        self.cached_manager_running_by_code = running_code
        self.cached_manager_running_by = running_by
        self.cached_manager_state = state
        self.cached_manager_updated = now
        return True

    def begin_manager_recovery(self, reason, force_manual=None):
        """Protect a physically running generator while manager state recovers."""
        if self.actual_state not in (
            "STARTING",
            "RUNNING",
            "RUNNING_SETTLED",
        ) and force_manual is None:
            return False

        now = time.monotonic()

        try:
            local_start = int(self.service["/Start"])
        except Exception:
            local_start = 0

        code = self.cached_manager_running_by_code
        manual = self.cached_manager_manual_start

        if force_manual is None:
            if manual == 1 or code == 1 or self.external_manual_adopted:
                restore_manual = True
            elif code not in (None, 0, 1):
                # Preserve an automatic/test-run owner as automatic; do not
                # silently turn it into a ManualStart run.
                restore_manual = False
            else:
                # Fallback if the manager vanished before our first cache
                # refresh. /Start=1 proves that the old manager was commanding
                # the remote genset to run.
                restore_manual = local_start == 1
        else:
            restore_manual = bool(force_manual)

        timer = 0
        if restore_manual and self.cached_manager_manual_timer is not None:
            timer = max(0, int(self.cached_manager_manual_timer))

        self.manager_recovery_active = True
        self.manager_recovery_until = now + MANAGER_RECOVERY_SECONDS
        self.manager_recovery_reason = str(reason)
        self.manager_recovery_restore_manual = restore_manual
        self.manager_recovery_timer = timer
        self.manager_recovery_running_by_code = code

        self.log(
            "MANAGER RECOVERY armed: reason='{}', restore_manual={}, "
            "timer={}s, cached_running_by_code={}".format(
                self.manager_recovery_reason,
                int(self.manager_recovery_restore_manual),
                self.manager_recovery_timer,
                self.manager_recovery_running_by_code,
            )
        )
        self.write_status()
        return True

    def complete_manager_recovery(self, reason):
        if not self.manager_recovery_active:
            return
        self.log("MANAGER RECOVERY complete: {}".format(reason))
        self.manager_recovery_active = False
        self.manager_recovery_until = 0.0
        self.manager_recovery_reason = None
        self.manager_recovery_restore_manual = False
        self.manager_recovery_timer = 0
        self.manager_recovery_running_by_code = None
        self.write_status()

    def restore_manager_after_restart(self):
        """Restore the old manager's ownership after startstop1 is recreated."""
        if not self.manager_recovery_active or self.manager_service is None:
            return False

        if self.manager_recovery_restore_manual:
            # Victron's native timed-start UI writes the timer first, then
            # ManualStart=1. Reproduce that exact ordering. dbus_set() wraps
            # values in dbus.Int32 so the timer cannot become a string.
            if self.manager_recovery_timer > 0:
                try:
                    ok = self.dbus_set(
                        self.manager_service,
                        "/ManualStartTimer",
                        self.manager_recovery_timer,
                    )
                except Exception as e:
                    self.log(
                        "MANAGER RECOVERY: could not restore ManualStartTimer: "
                        "{}".format(e)
                    )
                    ok = False

                if ok:
                    self.log(
                        "MANAGER RECOVERY: restored ManualStartTimer={}s".format(
                            self.manager_recovery_timer
                        )
                    )

            # If an external-start queue contains the same request, this
            # recovery path supersedes it and preserves timer-before-start
            # ordering.
            if self.queued_manual_value == 1:
                self.queued_manual_value = None

            ok = self.set_manager_manual_start(1)
            if ok:
                self.log(
                    "MANAGER RECOVERY: restored manual ownership; waiting for "
                    "replacement manager /Start=1 synchronization"
                )
            return ok

        # For an automatic/test-run owner, let the replacement dbus-generator
        # re-evaluate its own conditions. Its initial /Start=0 is blocked by
        # on_start_write while this recovery guard is active. A subsequent
        # /Start=1 proves ownership has been re-established.
        self.log(
            "MANAGER RECOVERY: prior owner was not manual; waiting for Victron "
            "to re-evaluate automatic conditions"
        )
        return True

    def on_name_owner_changed(self, name, old_owner, new_owner):
        name = str(name)
        if not name.startswith(MANAGER_PREFIX):
            return

        if self.manager_service == name and not str(new_owner):
            self.log("Victron generator manager disappeared: {}".format(name))

            # Preserve the last cached ownership instead of immediately
            # forgetting it. A replacement startstop service initializes its
            # remote switch to zero; that is NOT a trustworthy user STOP while
            # the physical generator is already running.
            if self.actual_state in (
                "STARTING",
                "RUNNING",
                "RUNNING_SETTLED",
            ):
                self.begin_manager_recovery(
                    "generator manager disappeared while physical genset "
                    "was {}".format(self.actual_state)
                )

            self.manager_service = None
            self.schedule_manager_discovery(immediate=False)
            self.write_status()
            return

        if str(new_owner):
            self.schedule_manager_discovery(immediate=False)

    def schedule_manager_discovery(self, immediate=False):
        if self.manager_service is not None:
            return
        if self.manager_discovery_id is not None:
            return

        delay_ms = 100 if immediate else 1000
        self.manager_discovery_id = GLib.timeout_add(
            delay_ms, self.discover_manager
        )

    def discover_manager(self):
        # One discovery attempt per timer invocation.  If the manager is not
        # present yet, reschedule at 1 Hz rather than polling D-Bus rapidly.
        self.manager_discovery_id = None

        try:
            names = self.bus.list_names()
        except Exception as e:
            self.log("Generator-manager discovery failed: {}".format(e))
            self.schedule_manager_discovery(immediate=False)
            return False

        for raw_name in names:
            name = str(raw_name)
            if not name.startswith(MANAGER_PREFIX):
                continue

            try:
                controlled_service = self.dbus_get(name, "/GensetService")
            except Exception:
                continue

            if str(controlled_service) == SERVICE_NAME:
                self.manager_service = name
                self.log(
                    "Matched Victron generator manager {} -> {}".format(
                        name, SERVICE_NAME
                    )
                )
                self.write_status()

                # Snapshot the newly-created manager before deciding what to
                # restore. During manager recovery, preserve the OLD cached
                # timer/owner until restore_manager_after_restart() has used it.
                if not self.manager_recovery_active:
                    self.refresh_manager_cache(force=True)

                if self.manager_recovery_active:
                    self.restore_manager_after_restart()

                if self.queued_manual_value is not None:
                    value = self.queued_manual_value
                    self.queued_manual_value = None
                    self.set_manager_manual_start(value)

                if self.startup_running_adoption_pending:
                    self.startup_running_adoption_pending = False
                    self.adopt_existing_running_generator()

                return False

        self.schedule_manager_discovery(immediate=False)
        return False

    def dbus_iface(self, service_name, path):
        obj = self.bus.get_object(service_name, path, introspect=False)
        return dbus.Interface(obj, dbus_interface=BUSITEM_IFACE)

    def dbus_get(self, service_name, path):
        return self.dbus_iface(service_name, path).GetValue()

    def dbus_set(self, service_name, path, value):
        rc = self.dbus_iface(service_name, path).SetValue(
            dbus.Int32(int(value), variant_level=1)
        )
        return int(rc) == 0

    def arm_expected_start_write(self, value):
        self.expected_start_write = int(value)
        self.expected_start_write_until = (
            time.monotonic() + ADOPTION_SUPPRESS_SECONDS
        )

    def expected_start_write_matches(self, value):
        if self.expected_start_write is None:
            return False
        if time.monotonic() > self.expected_start_write_until:
            self.expected_start_write = None
            self.expected_start_write_until = 0.0
            return False
        return int(value) == int(self.expected_start_write)

    def clear_expected_start_write(self):
        self.expected_start_write = None
        self.expected_start_write_until = 0.0

    def set_manager_manual_start(self, value):
        value = int(value)

        if self.manager_service is None:
            self.queued_manual_value = value
            self.schedule_manager_discovery(immediate=False)
            self.log(
                "Victron generator manager not available yet; queued "
                "/ManualStart={}".format(value)
            )
            return False

        try:
            current = int(self.dbus_get(self.manager_service, "/ManualStart"))
        except Exception as e:
            self.log("Could not read manager /ManualStart: {}".format(e))
            self.manager_service = None
            self.queued_manual_value = value
            self.schedule_manager_discovery(immediate=False)
            return False

        # Arm BEFORE changing ManualStart.  The manager may react quickly and
        # write our /Start path during the same GLib event cycle.
        self.arm_expected_start_write(value)

        if current == value:
            self.log(
                "Victron manager /ManualStart already {}; waiting for "
                "command synchronization".format(value)
            )
            self.external_manual_adopted = bool(value)
            self.write_status()
            return True

        try:
            ok = self.dbus_set(self.manager_service, "/ManualStart", value)
        except Exception as e:
            self.log("Could not set manager /ManualStart={}: {}".format(value, e))
            self.clear_expected_start_write()
            return False

        if not ok:
            self.log("Victron manager rejected /ManualStart={}".format(value))
            self.clear_expected_start_write()
            return False

        self.external_manual_adopted = bool(value)
        self.log(
            "Adopted external generator {} into Victron manual control "
            "(/ManualStart={})".format(
                "START" if value else "STOP", value
            )
        )
        self.write_status()
        return True

    def adopt_external_start(self):
        # A physical Scheiber START is a manual start from Victron's point of
        # view. Do NOT touch our /Start path here; the manager owns that path.
        #
        # If dbus-generator is temporarily absent, protect this physical start
        # from the replacement manager's initialization /Start=0.
        if self.manager_service is None:
            self.begin_manager_recovery(
                "external Scheiber START while generator manager unavailable",
                force_manual=True,
            )
        self.set_manager_manual_start(1)

    def adopt_existing_running_generator(self):
        """Adopt a generator discovered already running after bridge startup."""
        if self.manager_service is None:
            self.startup_running_adoption_pending = True
            self.schedule_manager_discovery(immediate=False)
            self.log(
                "Generator is already running; Victron manager not available "
                "yet, startup adoption queued"
            )
            return False

        try:
            manual = int(self.dbus_get(self.manager_service, "/ManualStart"))
        except Exception:
            manual = 0

        try:
            running_by = int(
                self.dbus_get(
                    self.manager_service,
                    "/RunningByConditionCode",
                )
            )
        except Exception:
            running_by = 0

        if manual == 1:
            self.external_manual_adopted = True
            self.log(
                "Startup resync: Victron ManualStart is already active; "
                "no additional CAN command required"
            )
            return True

        # A nonzero, non-manual condition means Victron already owns the run.
        if running_by not in (0, 1):
            self.log(
                "Startup resync: Victron already owns generator run via "
                "condition code {}; not forcing ManualStart".format(running_by)
            )
            return True

        self.log(
            "Startup resync: adopting already-running physical generator "
            "into Victron manual control"
        )
        return self.set_manager_manual_start(1)

    def resync_running_generator(self, reason, settled=False):
        if not self.startup_resync_active and self.actual_state in (
            "RUNNING",
            "RUNNING_SETTLED",
        ):
            return

        self.startup_resync_active = False
        self.service["/Scheiber/StartupResyncActive"] = 0
        self.startup_charger_ac_samples = 0

        # Adopt first so the running state cannot be mistaken for an unowned
        # run by the Victron generator manager. If the manager does not exist
        # yet, arm the same recovery guard used for a manager crash so its
        # eventual initialization /Start=0 cannot stop the physical genset.
        if self.manager_service is None:
            self.begin_manager_recovery(
                "startup resync found physical generator already running",
                force_manual=True,
            )
            self.queued_manual_value = 1
            self.schedule_manager_discovery(immediate=False)
        else:
            self.adopt_existing_running_generator()

        self.running_candidate_since = None
        self.pending = None
        self.pending_since = None
        self.pending_origin = None

        self.set_state(
            "RUNNING_SETTLED" if settled else "RUNNING",
            "startup resync: " + reason,
        )
        self.log(
            "STARTUP RESYNC: generator already running ({})".format(reason)
        )

    def adopt_external_stop(self):
        # Only clear ManualStart when manual start is actually active.
        # If an automatic Victron condition wants the generator running, we do
        # not silently disable that condition; Victron may legitimately restart.
        if self.manager_service is None:
            if self.external_manual_adopted:
                self.queued_manual_value = 0
                self.schedule_manager_discovery(immediate=False)
            return

        try:
            manual = int(self.dbus_get(self.manager_service, "/ManualStart"))
        except Exception as e:
            self.log("Could not read manager /ManualStart during STOP: {}".format(e))
            if self.external_manual_adopted:
                self.queued_manual_value = 0
            return

        if manual == 1 or self.external_manual_adopted:
            self.set_manager_manual_start(0)
        else:
            self.log(
                "External STOP observed while Victron ManualStart=0; "
                "actual status will update, automatic conditions are left intact"
            )

    # ------------------------------------------------------------------
    # SocketCAN
    # ------------------------------------------------------------------

    def connect_can(self):
        self.can_retry_id = None

        if self.can is not None:
            return False

        try:
            s = socket.socket(socket.PF_CAN, socket.SOCK_RAW, socket.CAN_RAW)

            filters = b"".join(
                struct.pack(
                    "=II",
                    can_id | CAN_EFF_FLAG,
                    CAN_EFF_MASK | CAN_EFF_FLAG,
                )
                for can_id in CAN_FILTER_IDS
            )
            s.setsockopt(SOL_CAN_RAW, CAN_RAW_FILTER, filters)

            # Be explicit: do not receive frames transmitted by THIS raw socket.
            # This prevents our own Victron-triggered command from being mistaken
            # for a physical/external Scheiber command.
            s.setsockopt(SOL_CAN_RAW, CAN_RAW_RECV_OWN_MSGS, 0)

            s.setblocking(False)
            s.bind((CAN_IF,))

            self.can = s
            self.set_all_connected(1)

            self.can_watch_id = GLib.io_add_watch(
                s.fileno(),
                GLib.IO_IN | GLib.IO_ERR | GLib.IO_HUP,
                self.on_can_event,
            )

            self.log(
                "SocketCAN connected to {} with {} kernel-filtered CAN IDs".format(
                    CAN_IF, len(CAN_FILTER_IDS)
                )
            )
            self.log(
                "Telemetry filters include generator AC/starter, Scheiber applied "
                "AC-source feedback, panel voltages, 6 house banks, experimental "
                "Engine Battery A/B, fresh water and 2 diesel tanks"
            )
            self.write_status()
            return False

        except Exception as e:
            self.set_all_connected(0)
            try:
                s.close()
            except Exception:
                pass
            self.can = None
            self.log("CAN connection failed: {}; retrying in 2s".format(e))
            self.schedule_can_retry()
            self.write_status()
            return False

    def schedule_can_retry(self):
        if self.can_retry_id is None:
            self.can_retry_id = GLib.timeout_add_seconds(2, self.connect_can)

    def disconnect_can(self, reason):
        self.log("CAN disconnected: {}".format(reason))
        self.set_all_connected(0)

        if self.can is not None:
            try:
                self.can.close()
            except Exception:
                pass

        self.can = None
        self.can_watch_id = None
        self.write_status()
        self.schedule_can_retry()

    def send_can(self, can_id, data):
        if self.can is None:
            self.log("CONTROL REJECTED: CAN interface is not connected")
            return False

        now = time.monotonic()
        command = (can_id, bytes(data))

        if (
            command == self.last_tx_command
            and now - self.last_tx_time < SAME_COMMAND_GUARD
        ):
            self.log("Duplicate CAN command suppressed")
            return True

        frame = struct.pack(
            "=IB3x8s",
            can_id | CAN_EFF_FLAG,
            len(data),
            data.ljust(8, b"\x00"),
        )

        try:
            self.can.send(frame)
        except OSError as e:
            self.log("CAN TX failed: {}".format(e))
            return False

        self.last_tx_command = command
        self.last_tx_time = now
        self.log("TX {:08X}#{}".format(can_id, data.hex().upper()))
        return True

    # ------------------------------------------------------------------
    # D-Bus /Start command handling
    # ------------------------------------------------------------------

    def on_start_write(self, path, value):
        try:
            desired = int(value)
        except Exception:
            return False

        if desired not in (0, 1):
            return False

        # A replacement dbus-generator/startstop service initializes its
        # remote switch to zero. If its predecessor disappeared while the
        # physical genset was running, that zero is initialization state, not
        # a trustworthy user STOP. Suppress it until ownership is restored.
        if (
            desired == 0
            and self.manager_recovery_active
            and self.actual_state in (
                "STARTING",
                "RUNNING",
                "RUNNING_SETTLED",
            )
        ):
            self.log(
                "MANAGER RECOVERY: suppressed replacement-manager /Start=0 "
                "while physical generator is {}".format(self.actual_state)
            )
            self.write_status()
            return True

        # This is the crucial loop-prevention rule.  When a physical Scheiber
        # command is adopted via /ManualStart, dbus_generator writes the matching
        # command state to /Start.  Accept it, but DO NOT transmit CAN again.
        if self.expected_start_write_matches(desired):
            self.log(
                "Victron synchronized /Start={} after external CAN command; "
                "duplicate CAN TX suppressed".format(desired)
            )
            self.clear_expected_start_write()
            if desired == 1 and self.manager_recovery_active:
                self.complete_manager_recovery(
                    "replacement manager synchronized /Start=1"
                )
            self.write_status()
            return True

        # Physical state can also make a duplicate command unnecessary even if
        # the adoption window has expired.
        if desired == 1 and self.actual_state in (
            "STARTING",
            "RUNNING",
            "RUNNING_SETTLED",
        ):
            self.log(
                "Victron /Start=1 accepted without CAN TX because generator "
                "is already {}".format(self.actual_state)
            )
            if self.manager_recovery_active:
                self.complete_manager_recovery(
                    "replacement manager reasserted /Start=1"
                )
            return True

        if desired == 0 and self.actual_state in (
            "STOPPING",
            "STOPPED",
            "OFF_IDLE",
        ):
            self.log(
                "Victron /Start=0 accepted without CAN TX because generator "
                "is already {}".format(self.actual_state)
            )
            return True

        # Genuine Victron control request.
        if desired == 1:
            self.log("Victron requested START via {}".format(SERVICE_NAME))
            if not self.send_can(GEN_CONTROL_ID, GEN_START):
                return False
            self.begin_transition("START", "victron")
            self.set_state("STARTING", "Victron /Start=1")
        else:
            self.log("Victron requested STOP via {}".format(SERVICE_NAME))
            if not self.send_can(GEN_CONTROL_ID, GEN_STOP):
                return False
            self.begin_transition("STOP", "victron")
            self.set_state("STOPPING", "Victron /Start=0")

        # VeDbusService stores the new /Start value after this returns True.
        return True

    # ------------------------------------------------------------------
    # State machine
    # ------------------------------------------------------------------

    def begin_transition(self, kind, origin):
        self.pending = kind
        self.pending_since = time.monotonic()
        self.pending_origin = origin
        self.running_candidate_since = None
        self.write_status()

    def clear_transition(self):
        self.pending = None
        self.pending_since = None
        self.pending_origin = None
        self.running_candidate_since = None
        self.write_status()

    @staticmethod
    def status_for_state(state):
        if state in ("STOPPED", "OFF_IDLE"):
            return STATUS_STOPPED
        if state == "STARTING":
            return STATUS_STARTING
        if state in ("RUNNING", "RUNNING_SETTLED"):
            return STATUS_RUNNING
        if state == "STOPPING":
            return STATUS_STOPPING
        return None

    def set_state(self, new_state, reason):
        old_state = self.actual_state
        self.actual_state = new_state
        self.state_reason = reason

        self.service["/Scheiber/State"] = new_state
        self.service["/Scheiber/StateReason"] = reason

        status = self.status_for_state(new_state)
        if status is not None:
            self.service["/StatusCode"] = status

        # Keep generator AC voltage tied to actual generator state.  The raw
        # 0x02040898 value may represent another AC source while the genset is
        # stopped, so never leave that voltage published as genset voltage.
        self.update_genset_ac_voltage_publication()
        if new_state in ("STOPPED", "OFF_IDLE"):
            self.service["/Ac/Frequency"] = 0.0
            self.service["/Ac/L1/Frequency"] = 0.0

        # IMPORTANT: there is intentionally NO assignment to /Start here.
        # /StatusCode is feedback; /Start is command state owned by Victron.

        if new_state != old_state:
            self.log(
                "ACTUAL GENERATOR STATE: {} -> {} ({})".format(
                    old_state, new_state, reason
                )
            )

        self.write_status()

    def confirm_running(self, reason):
        self.running_candidate_since = None
        self.pending = None
        self.pending_since = None
        self.pending_origin = None
        self.set_state("RUNNING", reason)

    def confirm_stopped(self, reason, settled=False):
        self.running_candidate_since = None
        self.pending = None
        self.pending_since = None
        self.pending_origin = None
        self.set_state("OFF_IDLE" if settled else "STOPPED", reason)

    # ------------------------------------------------------------------
    # CAN receive path
    # ------------------------------------------------------------------

    def on_can_event(self, source, condition):
        if condition & (GLib.IO_ERR | GLib.IO_HUP):
            self.disconnect_can("GLib IO error/hangup")
            return False

        try:
            while True:
                try:
                    frame = self.can.recv(16)
                except BlockingIOError:
                    break

                if len(frame) != 16:
                    continue

                self.process_can(frame)

        except OSError as e:
            self.disconnect_can(str(e))
            return False

        return True

    def process_can(self, frame):
        can_id_raw, dlc, payload = struct.unpack("=IB3x8s", frame)
        can_id = can_id_raw & CAN_EFF_MASK
        data = payload[:dlc]

        # --------------------------------------------------------------
        # Generator command observed from another CAN participant.
        # CAN_RAW_RECV_OWN_MSGS=0 means this socket does not receive its
        # own transmitted commands.
        # --------------------------------------------------------------
        if can_id == GEN_CONTROL_ID and len(data) >= 1:
            command = data[0]

            if command == 0x01:
                self.log("RX external generator command 02460B88#01 (START)")
                self.begin_transition("START", "external-can")
                self.set_state("STARTING", "external Scheiber START command")
                self.adopt_external_start()

            elif command == 0x02:
                self.log("RX external generator command 02460B88#02 (STOP)")
                self.begin_transition("STOP", "external-can")
                self.set_state("STOPPING", "external Scheiber STOP command")
                self.adopt_external_stop()

            return

        # --------------------------------------------------------------
        # Scheiber generator state-machine feedback
        # --------------------------------------------------------------
        if can_id == GEN_STATE_ID and len(data) >= 1:
            code = data[0]
            self.last_state_code = code
            self.service["/Scheiber/StateCode"] = code
            self.log("RX generator state 02440B88#{:02X}".format(code))

            # Observed normal START transition.
            if code in (0x02, 0x03):
                if self.actual_state not in (
                    "RUNNING",
                    "RUNNING_SETTLED",
                    "STOPPING",
                ):
                    self.set_state(
                        "STARTING", "Scheiber state {:02X}".format(code)
                    )

            # Observed normal STOP transition.
            elif code in (0x05, 0x04):
                if self.actual_state not in ("STOPPED", "OFF_IDLE"):
                    self.set_state(
                        "STOPPING", "Scheiber state {:02X}".format(code)
                    )

            # Newly observed when a START was interrupted by STOP.
            # Treat only as a stop/abort transition; exact semantics remain
            # intentionally unnamed.
            elif code in (0x07, 0x06):
                if self.pending == "STOP" or self.actual_state in (
                    "STARTING",
                    "STOPPING",
                ):
                    self.set_state(
                        "STOPPING",
                        "Scheiber abort/stop transition {:02X}".format(code),
                    )
                else:
                    self.log(
                        "Scheiber state {:02X} observed outside known "
                        "abort/stop context; not changing state".format(code)
                    )

            # Strong settled-running candidate.  Use it as a fallback only when
            # the state machine already indicates a start/run context.  Normal
            # confirmation still comes from generator-specific nominal frequency.
            elif code == 0x01:
                if self.startup_resync_active:
                    self.resync_running_generator(
                        "Scheiber settled-running state 01",
                        settled=True,
                    )
                elif self.actual_state in (
                    "STARTING",
                    "RUNNING",
                    "RUNNING_SETTLED",
                ) or self.pending == "START":
                    self.clear_transition()
                    self.set_state(
                        "RUNNING_SETTLED",
                        "Scheiber settled-running state 01",
                    )
                    self.log("Generator reached settled RUNNING state 01")
                else:
                    self.log(
                        "State 01 observed without an established start/run "
                        "context; not promoting state"
                    )

            # Strong settled-off state.  This is especially useful after an
            # aborted start where a separate 0-Hz event may never be emitted.
            elif code == 0x00:
                if self.startup_resync_active:
                    self.startup_resync_active = False
                    self.service["/Scheiber/StartupResyncActive"] = 0
                self.clear_transition()
                self.confirm_stopped(
                    "Scheiber settled-off state 00", settled=True
                )
                self.log("Generator reached settled OFF / IDLE state 00")

            self.write_status()
            return

        # --------------------------------------------------------------
        # Scheiber source selector APPLIED feedback -- RECEIVE ONLY
        # --------------------------------------------------------------
        if can_id in (AC_PANEL_APPLIED_ID, HOUSE_PANEL_APPLIED_ID) and len(data) >= 1:
            source = int(data[0])
            source_name = {
                SOURCE_OFF: "OFF",
                SOURCE_SHORE: "SHORE",
                SOURCE_GENERATOR: "GENERATOR",
            }.get(source, "UNKNOWN")

            if can_id == AC_PANEL_APPLIED_ID:
                self.ac_panel_applied_source = source
                self.log(
                    "RX AC panel applied source: {} ({:02X})".format(
                        source_name, source
                    )
                )
            else:
                self.house_panel_applied_source = source
                self.log(
                    "RX House panel applied source: {} ({:02X})".format(
                        source_name, source
                    )
                )

            self.update_ac_sources()
            self.update_genset_ac_voltage_publication()
            self.update_shore_power_publication()
            self.write_status()
            return

        # --------------------------------------------------------------
        # Mastervolt Inverter / AC ramp transition marker (0x02140898)
        # --------------------------------------------------------------
        if can_id == AC_RAMP_MARKER_ID and len(data) >= 1:
            marker = int(data[0])
            if marker == AC_RAMP_UP:  # 0x03
                self.mastervolt_inverter_state = 1
                self.log("RX Mastervolt Inverter state: ON / INVERTING (0x03)")
            elif marker == AC_RAMP_DOWN:  # 0x02
                self.mastervolt_inverter_state = 0
                self.log("RX Mastervolt Inverter state: OFF / STANDBY (0x02)")
            else:
                self.log("RX AC ramp transition marker: 0x{:02X}".format(marker))

            self.update_ac_sources()
            self.update_mastervolt_inverter_publication()
            self.write_status()
            return

        # --------------------------------------------------------------
        # Scheiber AC/House panel voltage telemetry
        # --------------------------------------------------------------
        if can_id in (AC_PANEL_TELEMETRY_ID, HOUSE_PANEL_TELEMETRY_ID) and len(data) >= 6:
            voltage = float((data[4] << 8) | data[5])
            freq_status = (
                float((data[6] << 8) | data[7])
                if len(data) >= 8
                else None
            )
            now = time.monotonic()

            if can_id == AC_PANEL_TELEMETRY_ID:
                self.last_ac_panel_voltage = voltage
                self.last_ac_panel_freq_status = freq_status
                self.ac_panel_last_update = now
                self.service["/Scheiber/AcPanelVoltage"] = voltage
                self.service["/Scheiber/AcPanelFrequencyStatus"] = freq_status
            else:
                self.last_house_panel_voltage = voltage
                self.last_house_panel_freq_status = freq_status
                self.house_panel_last_update = now
                self.service["/Scheiber/HousePanelVoltage"] = voltage
                self.service["/Scheiber/HousePanelFrequencyStatus"] = freq_status

            self.update_genset_ac_voltage_publication()
            self.update_shore_power_publication()
            self.update_mastervolt_inverter_publication()
            return

        # --------------------------------------------------------------
        # Generator/AC module voltage + coarse frequency
        # --------------------------------------------------------------
        if can_id == GEN_AC_ID and len(data) >= 4:
            voltage = (data[0] << 8) | data[1]
            coarse_frequency = (data[2] << 8) | data[3]

            self.last_ac_module_voltage = float(voltage)
            self.last_ac_module_frequency = float(coarse_frequency)
            self.gen_ac_last_update = time.monotonic()
            self.service["/Scheiber/AcModuleVoltage"] = float(voltage)
            self.service["/Scheiber/AcModuleFrequency"] = float(coarse_frequency)
            self.update_genset_ac_voltage_publication()
            return

        # --------------------------------------------------------------
        # Generator starter-battery / charger telemetry
        # --------------------------------------------------------------
        if can_id == GEN_STARTER_ID and len(data) >= 2:
            raw0 = data[0] | (data[1] << 8)
            raw1 = (
                data[2] | (data[3] << 8)
                if len(data) >= 4
                else None
            )
            raw2 = (
                data[4] | (data[5] << 8)
                if len(data) >= 6
                else None
            )

            starter_voltage = raw0 * 0.1
            self.gen_starter_last_update = time.monotonic()
            if 5.0 <= starter_voltage <= 18.5:
                self.last_starter_voltage = round(starter_voltage, 2)
                self.service["/StarterVoltage"] = self.last_starter_voltage
                self.update_battery_service(
                    "generator",
                    voltage=self.last_starter_voltage,
                    raw_words=[raw0, raw1 or 0, raw2 or 0],
                )
            else:
                # Keep obviously invalid/off values out of the native UI, but
                # retain raw words for diagnostics.
                self.last_starter_voltage = None
                self.service["/StarterVoltage"] = None
                svc = self.battery_services.get("generator")
                if svc is not None:
                    svc["/Dc/0/Voltage"] = None
                    svc["/Scheiber/RawWord0"] = int(raw0)
                    if raw1 is not None:
                        svc["/Scheiber/RawWord1"] = int(raw1)
                    if raw2 is not None:
                        svc["/Scheiber/RawWord2"] = int(raw2)

            if raw1 is not None:
                charger_current = raw1 * 0.1
                if 0.0 <= charger_current <= 200.0:
                    self.last_generator_charger_current = round(charger_current, 1)
                    self.service["/Scheiber/GeneratorChargerCurrent"] = (
                        self.last_generator_charger_current
                    )

            if raw2 is not None:
                charger_ac_voltage = raw2 * 0.1
                self.gen_charger_ac_last_update = time.monotonic()
                if 0.0 <= charger_ac_voltage <= 300.0:
                    self.last_generator_charger_ac_voltage = round(
                        charger_ac_voltage, 1
                    )
                    self.service["/Scheiber/GeneratorChargerAcVoltage"] = (
                        self.last_generator_charger_ac_voltage
                    )
                else:
                    self.last_generator_charger_ac_voltage = None
                    self.service["/Scheiber/GeneratorChargerAcVoltage"] = None

                if self.startup_resync_active:
                    if (
                        STARTUP_CHARGER_AC_MIN
                        <= charger_ac_voltage
                        <= STARTUP_CHARGER_AC_MAX
                    ):
                        self.startup_charger_ac_samples += 1
                        if (
                            self.startup_charger_ac_samples
                            >= STARTUP_CHARGER_AC_CONFIRM_SAMPLES
                        ):
                            self.resync_running_generator(
                                "generator-charger AC present on consecutive samples"
                            )
                    elif charger_ac_voltage < 20.0:
                        self.startup_charger_ac_samples = 0

                self.update_genset_ac_voltage_publication()
            return

        # --------------------------------------------------------------
        # Confirmed tank levels: fresh water, diesel 1, diesel 2
        # --------------------------------------------------------------
        if can_id == TANK_LEVEL_ID and len(data) >= 6:
            fresh = (data[0] << 8) | data[1]
            diesel1 = (data[2] << 8) | data[3]
            diesel2 = (data[4] << 8) | data[5]

            self.update_tank_service("fresh", fresh)
            self.update_tank_service("diesel1", diesel1)
            self.update_tank_service("diesel2", diesel2)
            return

        # --------------------------------------------------------------
        # Six house-bank battery sensor frames
        # --------------------------------------------------------------
        if can_id in HOUSE_KEY_BY_CAN and len(data) >= 6:
            key = HOUSE_KEY_BY_CAN[can_id]
            raw_v = data[0] | (data[1] << 8)
            raw_i = data[2] | (data[3] << 8)
            raw_soc = data[4] | (data[5] << 8)

            voltage = raw_v * HOUSE_VOLTAGE_SCALE
            current = (raw_i - HOUSE_CURRENT_ZERO) * HOUSE_CURRENT_SCALE
            soc = float(raw_soc) if 0 <= raw_soc <= 100 else None

            voltage_out = round(voltage, 2) if 5.0 <= voltage <= 18.5 else None
            current_out = (
                round(current, 1)
                if -500.0 <= current <= 500.0
                else None
            )

            self.update_battery_service(
                key,
                voltage=voltage_out,
                current=current_out,
                soc=soc,
                raw_words=[raw_v, raw_i, raw_soc],
            )
            return

        # --------------------------------------------------------------
        # 60A Multi-Output Charger B1: Starboard Engine Starter Battery
        # --------------------------------------------------------------
        if can_id == CHARGER_60A_TELEMETRY_ID and len(data) >= 2:
            raw0 = data[0] | (data[1] << 8)
            raw1 = (
                data[2] | (data[3] << 8)
                if len(data) >= 4
                else None
            )
            raw2 = (
                data[4] | (data[5] << 8)
                if len(data) >= 6
                else None
            )

            voltage = raw0 * CHARGER_60A_VOLTAGE_SCALE
            voltage_out = round(voltage, 2) if 5.0 <= voltage <= 18.5 else None

            self.update_battery_service(
                "engine_starboard",
                voltage=voltage_out,
                raw_words=[raw0, raw1 or 0, raw2 or 0],
            )
            return

        # --------------------------------------------------------------
        # 60A Multi-Output Charger B3: Port Engine Starter Battery (& B2 House)
        # --------------------------------------------------------------
        if can_id == CHARGER_60A_DYNAMIC_ID and len(data) >= 4:
            raw0 = data[0] | (data[1] << 8)  # House bank on charger (B2)
            raw1 = data[2] | (data[3] << 8)  # Port starter voltage (B3)
            raw2 = (
                data[4] | (data[5] << 8)
                if len(data) >= 6
                else None
            )

            voltage_port = raw1 * CHARGER_60A_VOLTAGE_SCALE
            voltage_port_out = (
                round(voltage_port, 2)
                if 5.0 <= voltage_port <= 18.5
                else None
            )

            self.update_battery_service(
                "engine_port",
                voltage=voltage_port_out,
                raw_words=[raw0, raw1, raw2 or 0],
            )
            return

        # --------------------------------------------------------------
        # Generator-associated frequency feedback
        # --------------------------------------------------------------
        if can_id == GEN_FREQ_ID and len(data) >= 2:
            raw = data[0] | (data[1] << 8)
            frequency = raw / 10.0
            self.last_frequency = frequency
            self.service["/Ac/Frequency"] = frequency
            self.service["/Ac/L1/Frequency"] = frequency

            self.log("RX generator frequency {:.1f} Hz".format(frequency))

            if RUNNING_FREQ_MIN <= frequency <= RUNNING_FREQ_MAX:
                if self.startup_resync_active:
                    self.resync_running_generator(
                        "generator-specific nominal frequency {:.1f} Hz".format(
                            frequency
                        )
                    )
                # If already confirmed running, this is just fresh telemetry.
                elif self.actual_state in ("RUNNING", "RUNNING_SETTLED"):
                    self.running_candidate_since = None
                elif self.running_candidate_since is None:
                    self.running_candidate_since = time.monotonic()
                    self.log(
                        "Nominal generator frequency seen; starting {:.1f}s "
                        "RUNNING confirmation delay".format(
                            RUNNING_CONFIRM_DELAY
                        )
                    )

            elif frequency <= STOPPED_FREQ_MAX:
                if self.startup_resync_active:
                    self.startup_resync_active = False
                    self.service["/Scheiber/StartupResyncActive"] = 0
                self.confirm_stopped(
                    "generator-specific frequency {:.1f} Hz".format(frequency)
                )
                self.log("GENERATOR STOPPED CONFIRMED at {:.1f} Hz".format(frequency))

            else:
                if self.running_candidate_since is not None:
                    self.log(
                        "Frequency left nominal range before RUNNING "
                        "confirmation: {:.1f} Hz".format(frequency)
                    )
                self.running_candidate_since = None

            self.write_status()
            return

    # ------------------------------------------------------------------
    # Timers
    # ------------------------------------------------------------------

    def timer_tick(self):
        now = time.monotonic()

        # Keep a numeric snapshot of ManualStart/ManualStartTimer and ownership
        # while the manager is healthy. This is what lets a timed/manual run
        # survive a dbus-generator process restart.
        self.refresh_manager_cache()

        if (
            self.manager_recovery_active
            and now >= self.manager_recovery_until
        ):
            self.log(
                "WARNING: MANAGER RECOVERY guard timed out after {:.0f}s; "
                "physical generator state remains authoritative and no CAN "
                "STOP is being invented".format(MANAGER_RECOVERY_SECONDS)
            )
            self.complete_manager_recovery("recovery timeout")

        if (
            self.startup_resync_active
            and now - self.startup_resync_started >= STARTUP_RESYNC_SECONDS
        ):
            self.startup_resync_active = False
            self.service["/Scheiber/StartupResyncActive"] = 0
            self.startup_charger_ac_samples = 0
            self.log(
                "Startup resync window ended without positive running evidence"
            )
            self.write_status()

        # Nominal-frequency confirmation hold.
        if self.running_candidate_since is not None:
            held = now - self.running_candidate_since
            if held >= RUNNING_CONFIRM_DELAY:
                total = (
                    now - self.pending_since
                    if self.pending_since is not None
                    else None
                )

                self.confirm_running(
                    "generator-specific nominal frequency confirmed"
                )

                if total is None:
                    self.log("GENERATOR RUNNING CONFIRMED")
                else:
                    self.log(
                        "GENERATOR RUNNING CONFIRMED after {:.1f}s".format(total)
                    )

        # Diagnostic-only transition timeouts.  Do not invent an opposite
        # physical state and do not send retries.  Keep the last observed state
        # until real CAN feedback arrives.
        if self.pending is not None and self.pending_since is not None:
            elapsed = now - self.pending_since

            if self.pending == "START" and elapsed >= START_CONFIRM_TIMEOUT:
                self.log(
                    "WARNING: START transition has not reached RUNNING within "
                    "{:.1f}s; keeping STARTING status and sending no retry".format(
                        START_CONFIRM_TIMEOUT
                    )
                )
                self.pending = None
                self.pending_since = None
                self.pending_origin = None
                self.running_candidate_since = None
                self.write_status()

            elif self.pending == "STOP" and elapsed >= STOP_CONFIRM_TIMEOUT:
                self.log(
                    "WARNING: STOP transition has not reached STOPPED within "
                    "{:.1f}s; keeping STOPPING status and sending no retry".format(
                        STOP_CONFIRM_TIMEOUT
                    )
                )
                self.pending = None
                self.pending_since = None
                self.pending_origin = None
                self.write_status()

        # Battery telemetry is sample-and-hold.
        #
        # Do NOT invalidate /Dc/0/Voltage, /Dc/0/Current, or /Soc simply
        # because a sensor has not repeated its frame recently. Scheiber
        # battery frames can be sparse / change-driven, and blanking them
        # makes the Venus UI devices disappear and reappear.
        #
        # Fresh frames always overwrite the last published value. Tank levels
        # use the same sample-and-hold policy and are never blanked solely
        # because no new frame has arrived. Generator-specific telemetry below
        # still has its own freshness handling.

        if (
            self.gen_starter_last_update is not None
            and now - self.gen_starter_last_update > FAST_TELEMETRY_STALE_SECONDS
        ):
            self.last_starter_voltage = None
            self.service["/StarterVoltage"] = None

        # Re-evaluate preferred/fallback generator AC voltage freshness.
        self.update_genset_ac_voltage_publication()
        self.update_shore_power_publication()
        self.update_mastervolt_inverter_publication()

        # Keep status.json useful without writing it for every battery frame.
        if now - self.last_status_snapshot >= STATUS_SNAPSHOT_INTERVAL:
            self.write_status()
            self.last_status_snapshot = now

        # Expire stale adoption suppression even if no /Start write arrives.
        if (
            self.expected_start_write is not None
            and now > self.expected_start_write_until
        ):
            self.log(
                "External-command adoption window expired before matching "
                "Victron /Start write"
            )
            self.clear_expected_start_write()

        return True


def main():
    Bridge()
    GLib.MainLoop().run()


if __name__ == "__main__":
    main()
