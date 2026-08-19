import importlib.util
import subprocess
import sys
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
PROTOCOL_PATH = ROOT / "cerbo" / "scheiber_switch_protocol.py"
spec = importlib.util.spec_from_file_location("scheiber_switch_protocol", PROTOCOL_PATH)
protocol = importlib.util.module_from_spec(spec)
assert spec and spec.loader
sys.modules[spec.name] = protocol
spec.loader.exec_module(protocol)


class SwitchProtocolTests(unittest.TestCase):
    def test_complete_logical_mapping(self):
        self.assertEqual(len(protocol.CHANNELS), 10)
        self.assertEqual(len(protocol.PHYSICAL_OUTPUTS), 12)
        self.assertEqual(set(protocol.OUTPUT_BY_NUMBER), set(range(1, 13)))
        expected = {
            1: (0x02, 0x02161808, 1),
            2: (0x05, 0x02161808, 2),
            3: (0x03, 0x02181808, 1),
            4: (0x06, 0x02181808, 2),
            5: (0x04, 0x021A1808, 1),
            6: (0x08, 0x021A1808, 2),
            7: (0x0C, 0x021C1808, 1),
            8: (0x09, 0x021C1808, 2),
            9: (0x0D, 0x021E1808, 1),
            10: (0x0A, 0x021E1808, 2),
            11: (0x0B, 0x02201808, 1),
            12: (0x07, 0x02201808, 2),
        }
        for number, values in expected.items():
            output = protocol.OUTPUT_BY_NUMBER[number]
            self.assertEqual((output.key_code, output.state_can_id, output.state_slot), values)

    def test_water_pump_is_enable_toggle_not_auto_mode(self):
        water = protocol.CHANNEL_BY_ID["fresh_water_pump"]
        self.assertEqual(water.ui_type, protocol.UI_TYPE_TOGGLE)
        self.assertFalse(water.persisted_auto)
        self.assertEqual(water.output, 10)
        self.assertEqual(water.running_signal, "fresh_water_pump_running")

    def test_state_frame_layout(self):
        decoded = protocol.decode_output_state(0x02201808, bytes.fromhex("0000010100000000"))
        self.assertEqual(decoded, {11: True, 12: False})
        decoded = protocol.decode_output_state(0x02201808, bytes.fromhex("0000000000000101"))
        self.assertEqual(decoded, {11: False, 12: True})
        with self.assertRaises(ValueError):
            protocol.decode_output_state(0x02161808, b"\x00")

    def test_running_bits(self):
        self.assertEqual(
            protocol.decode_running(b"\x07"),
            {
                "fresh_water_pump_running": True,
                "bilge_port_running": True,
                "bilge_starboard_running": True,
            },
        )
        self.assertEqual(protocol.decode_running(b"\x00")["bilge_port_running"], False)
        with self.assertRaises(ValueError):
            protocol.decode_running(b"")

    def test_exact_key_payloads(self):
        press, release = protocol.build_key_payloads(0x05)
        self.assertEqual(press.hex().upper(), "0000000185")
        self.assertEqual(release.hex().upper(), "0000000105")

    def test_binary_commands_require_known_state(self):
        deck = protocol.CHANNEL_BY_ID["deck_floodlight"]
        with self.assertRaises(protocol.UnknownStateError):
            protocol.plan_binary(deck, None, True)
        self.assertEqual(protocol.plan_binary(deck, False, False), [])
        step = protocol.plan_binary(deck, False, True)[0]
        self.assertEqual(step.key_code, 0x05)
        self.assertEqual(step.expected_outputs, ((2, True),))

    def test_bilge_mode_decode(self):
        self.assertEqual(protocol.bilge_mode(False, False), protocol.MODE_OFF)
        self.assertEqual(protocol.bilge_mode(True, False), protocol.MODE_AUTO)
        self.assertEqual(protocol.bilge_mode(True, True), protocol.MODE_MANUAL)
        self.assertEqual(protocol.bilge_mode(False, True), protocol.MODE_INVALID)
        self.assertEqual(protocol.bilge_mode(None, False), protocol.MODE_UNKNOWN)

    def test_bilge_native_state_is_mode_plus_activity_lamp(self):
        self.assertEqual(protocol.bilge_mode_to_dbus(protocol.MODE_OFF, False), (0, 0))
        self.assertEqual(protocol.bilge_mode_to_dbus(protocol.MODE_AUTO, False), (0, 1))
        self.assertEqual(protocol.bilge_mode_to_dbus(protocol.MODE_AUTO, True), (1, 1))
        self.assertEqual(protocol.bilge_mode_to_dbus(protocol.MODE_MANUAL, False), (1, 0))
        self.assertEqual(protocol.bilge_mode_to_dbus(protocol.MODE_MANUAL, True), (1, 0))
        # Unexpected activity while OFF is deliberately visible on the ON lamp.
        self.assertEqual(protocol.bilge_mode_to_dbus(protocol.MODE_OFF, True), (1, 0))

    def test_every_bilge_transition_has_safe_intermediates(self):
        channel = protocol.CHANNEL_BY_ID["bilge_port"]
        modes = (protocol.MODE_OFF, protocol.MODE_AUTO, protocol.MODE_MANUAL)
        for source in modes:
            source_bits = protocol.bilge_target_bits(source)
            for target in modes:
                with self.subTest(source=source, target=target):
                    steps = protocol.plan_bilge(channel, source_bits[0], source_bits[1], target)
                    outputs = {6: source_bits[0], 7: source_bits[1]}
                    for step in steps:
                        outputs.update(dict(step.expected_outputs))
                        self.assertNotEqual(
                            protocol.bilge_mode(outputs[6], outputs[7]),
                            protocol.MODE_INVALID,
                        )
                    self.assertEqual((outputs[6], outputs[7]), protocol.bilge_target_bits(target))

    def test_exact_bilge_sequences(self):
        port = protocol.CHANNEL_BY_ID["bilge_port"]
        self.assertEqual(
            [step.key_code for step in protocol.plan_bilge(port, False, False, protocol.MODE_MANUAL)],
            [0x08, 0x0C],
        )
        self.assertEqual(
            [step.key_code for step in protocol.plan_bilge(port, True, True, protocol.MODE_OFF)],
            [0x0C, 0x08],
        )
        starboard = protocol.CHANNEL_BY_ID["bilge_starboard"]
        self.assertEqual(
            [step.key_code for step in protocol.plan_bilge(starboard, True, False, protocol.MODE_MANUAL)],
            [0x0D],
        )

    def test_invalid_bilge_state_is_never_commanded(self):
        channel = protocol.CHANNEL_BY_ID["bilge_port"]
        with self.assertRaises(protocol.InvalidStateError):
            protocol.plan_bilge(channel, False, True, protocol.MODE_OFF)
        with self.assertRaises(protocol.UnknownStateError):
            protocol.plan_bilge(channel, None, None, protocol.MODE_AUTO)

    def test_state_model_sync_and_running_are_independent(self):
        model = protocol.StateModel()
        self.assertEqual(model.missing_state_ids(), protocol.STATE_IDS)
        for can_id in protocol.STATE_IDS:
            model.apply(can_id, bytes.fromhex("0000000000000000"))
        self.assertEqual(model.missing_state_ids(), ())
        water = protocol.CHANNEL_BY_ID["fresh_water_pump"]
        self.assertFalse(model.binary_state(water))
        self.assertIsNone(model.running_state(water))
        model.apply(protocol.DIGITAL_INPUT_ID, b"\x01")
        self.assertTrue(model.running_state(water))
        self.assertFalse(model.binary_state(water))

    def test_steaming_and_navigation_remain_separate_feedback_channels(self):
        steaming = protocol.CHANNEL_BY_ID["steaming_light"]
        navigation = protocol.CHANNEL_BY_ID["navigation_lights"]
        self.assertEqual(steaming.output, 5)
        self.assertEqual(navigation.output, 3)
        self.assertEqual(protocol.plan_binary(steaming, False, True)[0].key_code, 0x04)
        self.assertEqual(protocol.plan_binary(navigation, False, True)[0].key_code, 0x03)


class RuntimeSourceTests(unittest.TestCase):
    def test_service_source_safety_guards(self):
        source = (ROOT / "cerbo" / "switch_service.py").read_text(encoding="utf-8")
        self.assertIn("com.victronenergy.switch.scheiber", source)
        self.assertIn('SWITCH_TX_ENABLED", "1"', source)
        self.assertIn("physical state is UNKNOWN", source)
        self.assertIn("no direct output forcing", source.lower())
        self.assertNotIn("0x02361808", source)
        self.assertNotIn("CMD_S_TOR", source)
        self.assertIn("no matching output-state feedback", source)

    def test_native_paths_and_running_inputs_are_present(self):
        source = (ROOT / "cerbo" / "switch_service.py").read_text(encoding="utf-8")
        self.assertIn("/SwitchableOutput/", source)
        self.assertIn("/GenericInput/", source)
        self.assertIn("bilge_port_running", source)
        self.assertIn("bilge_starboard_running", source)
        self.assertIn("fresh_water_pump_running", source)
        self.assertIn("Fresh Water Pump Activity", source)
        self.assertIn("Port Bilge Pump Activity", source)
        self.assertIn('Settings/PrimaryLabel", "Motor"', source)
        self.assertIn("bilge_mode_to_dbus(mode, running=bool(running))", source)

    def test_python_sources_compile(self):
        subprocess.run(
            [sys.executable, "-m", "py_compile",
             str(ROOT / "cerbo" / "scheiber_switch_protocol.py"),
             str(ROOT / "cerbo" / "switch_service.py")],
            check=True,
        )

    def test_shell_sources_parse(self):
        for path in (
            ROOT / "cerbo" / "install.sh",
            ROOT / "cerbo" / "uninstall.sh",
            ROOT / "cerbo" / "service-switch" / "run",
        ):
            subprocess.run(["sh", "-n", str(path)], check=True)

    def test_installer_deploys_both_services(self):
        source = (ROOT / "cerbo" / "install.sh").read_text(encoding="utf-8")
        self.assertIn("scheiber-switch", source)
        self.assertIn("scheiber_switch_protocol.py", source)
        self.assertIn("switch_service.py", source)
        self.assertIn("SWITCH_TX_ENABLED", source)
        self.assertIn("python3 -m py_compile", source)
        self.assertIn("EXPECTED_BRIDGE_SHA256", source)

    def test_handover_contains_required_field_gates(self):
        source = (ROOT / "docs" / "SWITCH_SERVICE_HANDOVER.md").read_text(encoding="utf-8")
        self.assertIn("Deck Floodlight", source)
        self.assertIn("AUTO-triggered", source)
        self.assertIn("Never assume OFF", source)
        self.assertIn("Node-RED", source)
        self.assertIn("Do not automatically stop", source)
        self.assertIn("Auto + On", source)
        self.assertIn("pressure system is enabled", source)


if __name__ == "__main__":
    unittest.main()
