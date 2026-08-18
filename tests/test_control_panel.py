import importlib.util
import json
import sys
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "scripts" / "scheiber_v8_panel.py"
spec = importlib.util.spec_from_file_location("scheiber_panel", MODULE_PATH)
panel = importlib.util.module_from_spec(spec)
assert spec and spec.loader
sys.modules[spec.name] = panel
spec.loader.exec_module(panel)


class ControlPanelTests(unittest.TestCase):
    def frame(self, can_id, hex_data):
        return panel.Frame(None, "can1", can_id, bytes.fromhex(hex_data))

    def test_alive_decodes_firmware(self):
        events = panel.decode_frame(self.frame(0x00001808, "080F018076"))
        self.assertEqual(events[0]["firmware"], "08.15.01")
        self.assertEqual(events[0]["configuration_crc"], "0x8076")
        fields = events[0]["multibloc"]
        self.assertEqual(fields, {"frame_type": 0, "reference": 48, "coding": 1, "subnetwork": 0})

    def test_switch_press_release(self):
        press = panel.decode_frame(self.frame(0x04001808, "000000018B"))[0]
        release = panel.decode_frame(self.frame(0x04001808, "000000010B"))[0]
        self.assertEqual((press["name"], press["action"], press["key"]), ("fridge_unit", "press", 0x0B))
        self.assertEqual((release["name"], release["action"], release["key"]), ("fridge_unit", "release", 0x0B))

    def test_output_pairs(self):
        events = panel.decode_frame(self.frame(0x02201808, "0000010100000000"))
        self.assertEqual(events[0]["output"], 11)
        self.assertTrue(events[0]["on"])
        self.assertEqual(events[1]["output"], 12)
        self.assertFalse(events[1]["on"])

        events = panel.decode_frame(self.frame(0x02201808, "0000000000000101"))
        self.assertFalse(events[0]["on"])
        self.assertTrue(events[1]["on"])

    def test_digital_input_feedback(self):
        for value, expected in [
            (0x01, "fresh_water_pump_running"),
            (0x02, "bilge_port_running"),
            (0x04, "bilge_starboard_running"),
        ]:
            event = panel.decode_frame(self.frame(0x02141808, f"{value:02X}"))[0]
            self.assertTrue(event["signals"][expected])

    def test_build_key_frames(self):
        press, release = panel.build_key_frames("fridge_unit")
        self.assertEqual(press.hex().upper(), "000000018B")
        self.assertEqual(release.hex().upper(), "000000010B")

    def test_machine_mapping_matches_decoder(self):
        mapping = json.loads((ROOT / "docs" / "control-panel-v8" / "panel_mapping.json").read_text())
        for function in mapping["functions"]:
            key = int(function["key"], 16)
            self.assertIn(key, panel.KEY_NAMES)
            self.assertEqual(panel.OUTPUT_NAMES[function["output"]], function["name"])
            self.assertIn(int(function["state_can_id"], 16), panel.STATE_IDS)

    def test_evidence_contains_key_correlations(self):
        frames = []
        for line in (ROOT / "data" / "raw" / "control-panel-v8" / "panel-switch-sequence-2026-08-18.log").read_text().splitlines():
            frame = panel.parse_candump_line(line)
            if frame:
                frames.append(frame)

        seen_presses = set()
        seen_on_outputs = set()
        for frame in frames:
            for event in panel.decode_frame(frame):
                if event["kind"] == "switch" and event["action"] == "press":
                    seen_presses.add(event["key"])
                if event["kind"] == "output_state" and event["on"]:
                    seen_on_outputs.add(event["output"])

        self.assertEqual(set(panel.KEY_NAMES), seen_presses)
        self.assertEqual(set(panel.OUTPUT_NAMES), seen_on_outputs)

    def test_water_pump_running_capture(self):
        values = []
        for line in (ROOT / "data" / "raw" / "control-panel-v8" / "water-pump-demand-2026-08-18.log").read_text().splitlines():
            frame = panel.parse_candump_line(line)
            if frame and frame.can_id == panel.DIGITAL_INPUT_ID:
                values.append(frame.data[0])
        self.assertEqual(values, [0x01, 0x00])


if __name__ == "__main__":
    unittest.main()
