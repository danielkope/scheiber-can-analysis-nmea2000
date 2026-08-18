import importlib.util
import sys
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "cerbo" / "switch_protocol.py"
spec = importlib.util.spec_from_file_location("switch_protocol", MODULE_PATH)
protocol = importlib.util.module_from_spec(spec)
assert spec and spec.loader
sys.modules[spec.name] = protocol
spec.loader.exec_module(protocol)


class SwitchProtocolTests(unittest.TestCase):
    def test_key_frames_match_capture(self):
        press, release = protocol.build_key_frames("anchor_light")
        self.assertEqual(press.hex().upper(), "0000000186")
        self.assertEqual(release.hex().upper(), "0000000106")

    def test_state_frame_decode(self):
        decoded = protocol.decode_output_state(0x02181808, bytes.fromhex("0000010100000101"))
        self.assertEqual(decoded, {3: True, 4: True})

    def test_running_bits(self):
        running = protocol.decode_running_inputs(bytes([0x07]))
        self.assertEqual(running, {
            "fresh_water_pump": True,
            "bilge_port": True,
            "bilge_starboard": True,
        })

    def test_bilge_mode_mapping(self):
        self.assertEqual(protocol.derive_bilge_mode(False, False), protocol.BilgeMode.OFF)
        self.assertEqual(protocol.derive_bilge_mode(True, False), protocol.BilgeMode.AUTO)
        self.assertEqual(protocol.derive_bilge_mode(True, True), protocol.BilgeMode.MANUAL)
        self.assertEqual(protocol.derive_bilge_mode(False, True), protocol.BilgeMode.INVALID)
        self.assertEqual(protocol.derive_bilge_mode(None, False), protocol.BilgeMode.UNKNOWN)

    def test_bilge_ui_values(self):
        self.assertEqual(protocol.bilge_ui_values(protocol.BilgeMode.OFF), (0, 0))
        self.assertEqual(protocol.bilge_ui_values(protocol.BilgeMode.AUTO), (0, 1))
        self.assertEqual(protocol.bilge_ui_values(protocol.BilgeMode.MANUAL), (1, 0))

    def test_binary_transition_requires_known_actual(self):
        anchor = protocol.CHANNEL_BY_ID["anchor_light"]
        with self.assertRaises(ValueError):
            protocol.plan_binary_transition(anchor, None, True)
        self.assertEqual(protocol.plan_binary_transition(anchor, False, False), [])
        action = protocol.plan_binary_transition(anchor, False, True)[0]
        self.assertEqual(action.keys, ("anchor_light",))
        self.assertEqual(action.expected_output, (4, True))

    def test_bilge_transition_paths(self):
        port = protocol.CHANNEL_BY_ID["bilge_port"]
        actions = protocol.plan_bilge_transition(port, protocol.BilgeMode.OFF, protocol.BilgeMode.MANUAL)
        self.assertEqual([a.expected_bilge_mode for a in actions], [protocol.BilgeMode.AUTO, protocol.BilgeMode.MANUAL])
        self.assertEqual(actions[0].keys, ("bilge_port_auto",))
        self.assertEqual(actions[1].keys, ("bilge_port_manual",))

        actions = protocol.plan_bilge_transition(port, protocol.BilgeMode.MANUAL, protocol.BilgeMode.OFF)
        self.assertEqual(actions[0].keys, ("bilge_port_auto", "bilge_port_manual"))
        self.assertEqual(actions[0].expected_bilge_mode, protocol.BilgeMode.OFF)

    def test_invalid_bilge_state_never_commands(self):
        port = protocol.CHANNEL_BY_ID["bilge_port"]
        with self.assertRaises(ValueError):
            protocol.plan_bilge_transition(port, protocol.BilgeMode.INVALID, protocol.BilgeMode.OFF)

    def test_model_separates_mode_from_running(self):
        model = protocol.SwitchStateModel()
        # Port AUTO output 6 lives in slot 2 of 0x021A1808.
        model.update_frame(0x021A1808, bytes.fromhex("0000000000000101"))
        # Port MANUAL output 7 lives in slot 1 of 0x021C1808 and is off.
        model.update_frame(0x021C1808, bytes.fromhex("0000000000000000"))
        self.assertEqual(model.bilge_mode("bilge_port"), protocol.BilgeMode.AUTO)
        self.assertIsNone(model.running_state("bilge_port"))
        model.update_frame(protocol.DIGITAL_INPUT_ID, bytes([0x02]))
        self.assertEqual(model.bilge_mode("bilge_port"), protocol.BilgeMode.AUTO)
        self.assertTrue(model.running_state("bilge_port"))

    def test_all_ten_logical_channels_present(self):
        self.assertEqual(len(protocol.CHANNELS), 10)
        self.assertEqual({c.channel_id for c in protocol.CHANNELS}, {
            "electronics", "deck_floodlight", "navigation_lights", "anchor_light",
            "steaming_light", "bilge_port", "bilge_starboard", "fresh_water_pump",
            "fridge_unit", "lighting",
        })


if __name__ == "__main__":
    unittest.main()
