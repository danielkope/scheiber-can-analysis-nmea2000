import importlib.util
import struct
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BRIDGE_PATH = ROOT / "cerbo" / "nmea2000_bridge.py"
spec = importlib.util.spec_from_file_location("nmea2000_bridge", BRIDGE_PATH)
n2k_bridge = importlib.util.module_from_spec(spec)
spec.loader.exec_module(n2k_bridge)


def test_build_name_u64():
    uniq_id = 1380393
    mfg_code = 358
    name = n2k_bridge.build_name_u64(uniq_id, mfg_code, 0, 130, 60, 0, 4)
    
    raw = struct.pack("<Q", name)
    assert len(raw) == 8
    
    assert (name & 0x1FFFFF) == uniq_id
    assert ((name >> 21) & 0x7FF) == mfg_code
    assert ((name >> 63) & 0x01) == 1


def test_encode_pgn127505_fluid_level():
    # Fresh Water: Instance 0, Fluid Type 1 (Water), 51.0%, 0.600 m3 (600 L)
    payload = n2k_bridge.encode_pgn127505_fluid_level(0, 1, 51.0, 0.6)
    assert len(payload) == 8
    byte0, l_raw, c_raw, res = struct.unpack("<BHIB", payload)
    assert (byte0 >> 4) == 0 # Instance 0
    assert (byte0 & 0x0F) == 1 # Fresh Water
    assert l_raw == 12750 # 51.0 * 250
    assert c_raw == 6000 # 600.0 L (0.1 L units)
    assert res == 0xFF
    
    # Diesel 2: Instance 1, Fluid Type 0 (Fuel), 78.0%, 0.500 m3 (500 L)
    payload_d2 = n2k_bridge.encode_pgn127505_fluid_level(1, 0, 78.0, 0.5)
    byte0_d2, l_raw_d2, c_raw_d2, res_d2 = struct.unpack("<BHIB", payload_d2)
    assert (byte0_d2 >> 4) == 1 # Instance 1
    assert (byte0_d2 & 0x0F) == 0 # Fuel
    assert l_raw_d2 == 19500 # 78.0 * 250
    assert c_raw_d2 == 5000 # 500.0 L


def test_encode_pgn127508_battery():
    payload = n2k_bridge.encode_pgn127508_battery(1, 13.3, 42)
    assert len(payload) == 8
    dec_inst, dec_v, dec_cur, dec_temp, dec_seq = struct.unpack("<BHHHB", payload)
    assert dec_inst == 1
    assert dec_v == 1330
    assert dec_cur == 0x7FFF
    assert dec_temp == 0xFFFF
    assert dec_seq == 42


def test_encode_pgn127501_switch_bank():
    switch_states = [0] * n2k_bridge.NUM_SWITCH_CHANNELS
    switch_states[0] = 1 # Anchor
    switch_states[1] = 0 # Nav
    switch_states[2] = 1 # Steaming
    switch_states[7] = 1 # Water Pump
    
    payload = n2k_bridge.encode_pgn127501_switch_bank(switch_states, 0)
    assert len(payload) == 8
    assert payload[0] == 0x00 # Bank 0
    assert payload[1] == 0b00010001 # ch0=01, ch1=00, ch2=01, ch3=00
    assert payload[2] == 0b01000000 # ch4=00, ch5=00, ch6=00, ch7=01


def test_decode_pgn127502_switch_control():
    payload = bytes([0x00, 0xF1, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF])
    bank_inst, commands = n2k_bridge.decode_pgn127502_switch_control(payload)
    
    assert bank_inst == 0
    assert commands[0] == 1 # Turn ON
    assert commands[1] == 0 # Turn OFF
    assert commands[2] == 3 # No-op
    assert commands[3] == 3 # No-op
    assert commands[7] == 3 # No-op
