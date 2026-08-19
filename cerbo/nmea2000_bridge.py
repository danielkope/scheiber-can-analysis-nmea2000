#!/usr/bin/env python3
"""Scheiber NMEA 2000 Gateway Bridge for Victron Cerbo GX.

Publishes:
  1. PGN 127505 (Fluid Level) for Fresh Water (Inst 0, Water), Diesel 1 (Inst 0, Fuel), Diesel 2 (Inst 1, Fuel).
  2. PGN 127508 (Battery Status) for Port Starter, Starboard Starter, and Generator Starter batteries.
  3. PGN 127501 (Binary Switch Bank Status) for all 15 Scheiber Multibloc V8 switch channels.
Consumes:
  1. PGN 127502 (Binary Switch Bank Control) from B&G Zeus3 chartplotter and updates D-Bus switch states.
"""

import os
import sys
import time
import socket
import struct

N2K_IF = os.environ.get("N2K_IF", "can1")
PREFERRED_ADDR = 105
DEVICE_UNIQUE_ID = 1380393
MANUFACTURER_CODE = 358  # Victron Energy
DEVICE_FUNCTION = 130    # Multifunction / Display
DEVICE_CLASS = 60        # Electrical Distribution
SYSTEM_INSTANCE = 0
INDUSTRY_GROUP = 4       # Marine

# Tank definitions to publish as PGN 127505 (Fluid Level)
# (fluid_instance, fluid_type, dbus_service, name)
# Fluid types: 0 = Fuel/Diesel, 1 = Fresh Water, 2 = Waste Water, 5 = Black Water
TANK_PGN_DEFS = [
    (0, 1, "com.victronenergy.tank.scheiber_fresh", "Fresh Water Tank"),
    (0, 0, "com.victronenergy.tank.scheiber_diesel1", "Diesel Tank 1 (Port)"),
    (1, 0, "com.victronenergy.tank.scheiber_diesel2", "Diesel Tank 2 (Starboard)"),
]

# Battery definitions to publish as PGN 127508 (Battery Status)
BATTERY_PGN_DEFS = [
    # instance, dbus_service, name
    (0, "com.victronenergy.battery.scheiber_engine_port", "Port Engine Starter"),
    (1, "com.victronenergy.battery.scheiber_engine_starboard", "Starboard Engine Starter"),
    (2, "com.victronenergy.battery.scheiber_generator_starter", "Generator Starter"),
]

SWITCH_SERVICE = "com.victronenergy.switch.scheiber"
NUM_SWITCH_CHANNELS = 15


def build_name_u64(uniq_id, mfg_code, dev_inst, dev_func, dev_class, sys_inst, ind_grp):
    name = (uniq_id & 0x1FFFFF)
    name |= ((mfg_code & 0x7FF) << 21)
    name |= ((dev_inst & 0xFF) << 32)
    name |= ((dev_func & 0xFF) << 40)
    name |= ((dev_class & 0x7F) << 49)
    name |= ((sys_inst & 0x0F) << 56)
    name |= ((ind_grp & 0x07) << 60)
    name |= (1 << 63)  # Arbitrary Address Capable
    return name


def encode_pgn127505_fluid_level(fluid_inst, fluid_type, level_pct, capacity_m3=None):
    """Encode standard NMEA 2000 PGN 127505 (Fluid Level).
    
    Byte 0: (fluid_inst << 4) | (fluid_type & 0x0F)
    Bytes 1-2: Level (uint16 LE, 0.004 % per bit, 0..25000 -> 0..100.0%)
    Bytes 3-6: Capacity (uint32 LE, 0.1 L per bit / 0.0001 m3 per bit, 0xFFFFFFFF = unknown)
    Byte 7: Reserved (0xFF)
    """
    byte0 = ((int(fluid_inst) & 0x0F) << 4) | (int(fluid_type) & 0x0F)
    
    # Level: 0.004% per bit (level_pct * 250)
    l_clamped = max(0.0, min(100.0, float(level_pct)))
    l_raw = int(round(l_clamped * 250.0))
    
    # Capacity: 0.1 L per bit (m3 * 10000)
    if capacity_m3 is not None and float(capacity_m3) > 0.0:
        c_raw = int(round(float(capacity_m3) * 10000.0))
    else:
        c_raw = 0xFFFFFFFF
        
    return struct.pack("<BHI B", byte0, l_raw, c_raw, 0xFF)


def encode_pgn127508_battery(inst, voltage_v, seq_id=0):
    v_raw = int(round(float(voltage_v) * 100.0))  # 0.01 V resolution
    return struct.pack(
        "<BHHHB",
        int(inst),
        v_raw,
        0x7FFF,  # Current unavailable
        0xFFFF,  # Temp unavailable
        int(seq_id) & 0xFF
    )


def encode_pgn127501_switch_bank(switch_states, bank_inst=0):
    raw_bits = bytearray(7)
    for i in range(7):
        raw_bits[i] = 0xFF  # Default all 4 switches in this byte to 11 (Not Installed)
        
    for ch in range(min(len(switch_states), NUM_SWITCH_CHANNELS)):
        byte_idx = ch // 4
        bit_offset = (ch % 4) * 2
        state = 0x01 if switch_states[ch] == 1 else 0x00
        raw_bits[byte_idx] &= ~(0x03 << bit_offset)
        raw_bits[byte_idx] |= (state << bit_offset)

    return bytes([bank_inst & 0xFF]) + bytes(raw_bits)


def decode_pgn127502_switch_control(payload):
    if len(payload) < 8:
        return 0, {}
    bank_inst = payload[0]
    cmd_bytes = payload[1:8]
    commands = {}
    for ch in range(NUM_SWITCH_CHANNELS):
        byte_idx = ch // 4
        bit_offset = (ch % 4) * 2
        cmd = (cmd_bytes[byte_idx] >> bit_offset) & 0x03
        commands[ch] = cmd
    return bank_inst, commands


class Nmea2000Bridge:
    def __init__(self, interface=N2K_IF):
        for p in (
            "/opt/victronenergy/dbus-systemcalc-py/ext/velib_python",
            "/opt/victronenergy/velib_python",
        ):
            if os.path.isfile(os.path.join(p, "vedbus.py")):
                sys.path.insert(0, p)
                break

        import dbus
        from dbus.mainloop.glib import DBusGMainLoop
        from gi.repository import GLib

        DBusGMainLoop(set_as_default=True)

        self.dbus = dbus
        self.GLib = GLib
        self.iface = interface
        self.addr = PREFERRED_ADDR
        self.claimed = False
        self.sock = None
        self.bus = dbus.SystemBus()
        
        self.name_u64 = build_name_u64(
            DEVICE_UNIQUE_ID,
            MANUFACTURER_CODE,
            0,
            DEVICE_FUNCTION,
            DEVICE_CLASS,
            SYSTEM_INSTANCE,
            INDUSTRY_GROUP
        )
        self.name_bytes = struct.pack("<Q", self.name_u64)
        
        self.switch_states = [0] * NUM_SWITCH_CHANNELS
        self.last_tank_pub = 0.0
        self.last_battery_pub = 0.0
        self.last_switch_pub = 0.0
        self.seq_id = 0
        
        self.init_socket()
        self.claim_address(verbose=True)
        self.init_dbus_watch()
        
        self.GLib.io_add_watch(self.sock.fileno(), self.GLib.IO_IN, self.on_can_frame)
        self.GLib.timeout_add(500, self.timer_tick)
        print(f"[N2K Bridge] Initialized on {self.iface} with preferred address {self.addr}", flush=True)

    def init_socket(self):
        self.sock = socket.socket(socket.AF_CAN, socket.SOCK_RAW, socket.CAN_RAW)
        try:
            self.sock.setsockopt(socket.SOL_CAN_RAW, socket.CAN_RAW_LOOPBACK, 0)
        except Exception:
            pass
        self.sock.bind((self.iface,))
        self.sock.setblocking(False)

    def send_can_frame(self, can_id, payload):
        can_id |= 0x80000000  # CAN_EFF_FLAG
        dlc = len(payload)
        frame = struct.pack("=IB3x8s", can_id, dlc, payload.ljust(8, b'\xFF'))
        try:
            self.sock.send(frame)
        except Exception as e:
            print(f"[N2K Bridge] Error sending CAN frame 0x{can_id:08X}: {e}", flush=True)

    def claim_address(self, verbose=False):
        # PGN 60928 (0xEE00): Priority 6, Broadcast -> 0x18EEFFxx
        can_id = (6 << 26) | (0xEE00 << 8) | self.addr
        self.send_can_frame(can_id, self.name_bytes)
        self.claimed = True
        if verbose:
            print(f"[N2K Bridge] Claimed NMEA 2000 address {self.addr} on {self.iface}", flush=True)

    def init_dbus_watch(self):
        self.refresh_switch_states()
        self.bus.add_signal_receiver(
            self.on_dbus_property_change,
            signal_name="PropertiesChanged",
            path_keyword="path",
            sender_keyword="sender"
        )

    def refresh_switch_states(self):
        for ch in range(NUM_SWITCH_CHANNELS):
            try:
                obj = self.bus.get_object(SWITCH_SERVICE, f"/{ch}/State")
                val = obj.GetValue(dbus_interface="com.victronenergy.BusItem")
                self.switch_states[ch] = 1 if int(val) == 1 else 0
            except Exception:
                pass

    def on_dbus_property_change(self, *args, **kwargs):
        path = kwargs.get("path", "")
        changed = {}
        if len(args) == 3 and isinstance(args[1], dict):
            changed = args[1]
        elif len(args) >= 1 and isinstance(args[0], dict):
            changed = args[0]
            
        val = changed.get("Value", None)
        if val is not None and path and path.startswith("/"):
            parts = path.strip("/").split("/")
            if len(parts) >= 2 and parts[0].isdigit() and parts[1] == "State":
                ch = int(parts[0])
                if 0 <= ch < NUM_SWITCH_CHANNELS:
                    new_val = 1 if int(val) == 1 else 0
                    if self.switch_states[ch] != new_val:
                        self.switch_states[ch] = new_val
                        print(f"[N2K Bridge] Switch channel {ch} changed to {new_val}; publishing PGN 127501", flush=True)
                        self.publish_switch_bank_status()

    def publish_tank_status(self):
        """Publish PGN 127505 (Fluid Level) for Fresh Water and Diesel tanks."""
        for fluid_inst, fluid_type, service_name, name in TANK_PGN_DEFS:
            try:
                obj = self.bus.get_object(service_name, "/Level")
                lvl = obj.GetValue(dbus_interface="com.victronenergy.BusItem")
                if lvl is not None:
                    cap = None
                    try:
                        obj_cap = self.bus.get_object(service_name, "/Capacity")
                        cap = obj_cap.GetValue(dbus_interface="com.victronenergy.BusItem")
                    except Exception:
                        pass
                    payload = encode_pgn127505_fluid_level(fluid_inst, fluid_type, float(lvl), cap)
                    # PGN 127505 (0x1F211): Priority 6, Broadcast -> 0x19F211xx
                    can_id = (6 << 26) | (0x1F211 << 8) | self.addr
                    self.send_can_frame(can_id, payload)
            except Exception:
                pass

    def publish_battery_status(self):
        """Publish PGN 127508 (Battery Status) for each starter battery."""
        for inst, service_name, name in BATTERY_PGN_DEFS:
            try:
                obj = self.bus.get_object(service_name, "/Dc/0/Voltage")
                val = obj.GetValue(dbus_interface="com.victronenergy.BusItem")
                if val is not None and float(val) > 0.0:
                    payload = encode_pgn127508_battery(inst, float(val), self.seq_id)
                    can_id = (6 << 26) | (0x1F214 << 8) | self.addr
                    self.send_can_frame(can_id, payload)
            except Exception:
                pass
        self.seq_id = (self.seq_id + 1) & 0xFF

    def publish_switch_bank_status(self):
        """Publish PGN 127501 (Binary Switch Bank Status) for Bank 0."""
        payload = encode_pgn127501_switch_bank(self.switch_states, 0)
        can_id = (6 << 26) | (0x1F20D << 8) | self.addr
        self.send_can_frame(can_id, payload)

    def handle_switch_bank_control(self, payload):
        """Handle incoming PGN 127502 (Binary Switch Bank Control) from B&G Zeus3."""
        bank_inst, commands = decode_pgn127502_switch_control(payload)
        if bank_inst != 0:
            return
            
        for ch, cmd in commands.items():
            # 00 = Turn OFF, 01 = Turn ON
            if cmd in (0x00, 0x01):
                target_state = cmd
                if self.switch_states[ch] != target_state:
                    print(f"[N2K Bridge] Received N2K Switch Bank Control for channel {ch} -> {target_state}", flush=True)
                    try:
                        obj = self.bus.get_object(SWITCH_SERVICE, f"/{ch}/State")
                        obj.SetValue(self.dbus.Int32(target_state), dbus_interface="com.victronenergy.BusItem")
                    except Exception as e:
                        print(f"[N2K Bridge] Failed to set D-Bus switch {ch}: {e}", flush=True)

    def on_can_frame(self, fd, condition):
        try:
            data, _ = self.sock.recvfrom(64)
            if len(data) < 16:
                return True
            can_id, dlc, payload = struct.unpack("=IB3x8s", data[:16])
            can_id &= 0x1FFFFFFF
            pf = (can_id >> 16) & 0xFF
            ps = (can_id >> 8) & 0xFF
            dp = (can_id >> 24) & 1
            src = can_id & 0xFF
            
            if pf < 240:
                pgn = (dp << 16) | (pf << 8)
                dest = ps
            else:
                pgn = (dp << 16) | (pf << 8) | ps
                dest = 0xFF
                
            # ISO Request (PGN 59904 - 0xEA00)
            if pgn == 59904 and (dest == self.addr or dest == 0xFF):
                if len(payload) >= 3:
                    req_pgn = payload[0] | (payload[1] << 8) | (payload[2] << 16)
                    if req_pgn == 60928:
                        self.claim_address()
                    elif req_pgn == 127501:
                        self.publish_switch_bank_status()
                    elif req_pgn == 127505:
                        self.publish_tank_status()
                    elif req_pgn == 127508:
                        self.publish_battery_status()
                        
            # ISO Address Claim Conflict Check (PGN 60928 - 0xEE00)
            elif pgn == 60928 and src == self.addr:
                if payload[:8] == self.name_bytes:
                    return True
                remote_name = struct.unpack("<Q", payload[:8])[0]
                if remote_name < self.name_u64:
                    self.addr = (self.addr + 1) if self.addr < 250 else 100
                    print(f"[N2K Bridge] Address conflict with 0x{remote_name:016X}; changing address to {self.addr}", flush=True)
                    self.claim_address(verbose=True)
                    
            # PGN 127502 (Binary Switch Bank Control - 0x1F20E)
            elif pgn == 127502 and (dest == self.addr or dest == 0xFF):
                self.handle_switch_bank_control(payload[:8])
                
        except Exception as e:
            pass
        return True

    def timer_tick(self):
        now = time.monotonic()
        
        # Publish tanks every 2.0s (0.5 Hz)
        if now - self.last_tank_pub >= 2.0:
            self.publish_tank_status()
            self.last_tank_pub = now
            
        # Publish batteries every 1.0s (1.0 Hz)
        if now - self.last_battery_pub >= 1.0:
            self.publish_battery_status()
            self.last_battery_pub = now
            
        # Publish switch bank status every 1.0s (1.0 Hz)
        if now - self.last_switch_pub >= 1.0:
            self.publish_switch_bank_status()
            self.last_switch_pub = now
            
        return True


def main():
    bridge = Nmea2000Bridge()
    from gi.repository import GLib
    GLib.MainLoop().run()


if __name__ == "__main__":
    main()
