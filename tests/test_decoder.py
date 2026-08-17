from __future__ import annotations
import importlib.util
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("scheiber_can_analyze", ROOT / "scripts/scheiber_can_analyze.py")
assert spec is not None and spec.loader is not None
mod = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = mod
spec.loader.exec_module(mod)
CAP = {"water_l": 600.0, "diesel_1_l": 500.0, "diesel_2_l": 500.0}


class DecoderTests(unittest.TestCase):
    def frame(self, cid: int, payload: str, *, line: int = 1, timestamp: float = 1000.0):
        return mod.CandumpFrame(line, timestamp, "can1", cid, bytes.fromhex(payload))

    def values(self, cid: int, payload: str):
        return {r.name: r.value for r in mod.decode_frame(self.frame(cid, payload), 1000.0, CAP)}

    def test_tanks(self):
        values = self.values(0x02040580, "0054003F004F0001")
        self.assertEqual(values["water_level"], 84)
        self.assertEqual(values["water_volume"], 504.0)
        self.assertEqual(values["diesel_1_level"], 63)
        self.assertEqual(values["diesel_1_volume"], 315.0)
        self.assertEqual(values["diesel_2_level"], 79)
        self.assertEqual(values["diesel_2_volume"], 395.0)

    def test_panel_enum(self):
        values = self.values(0x02420B90, "04")
        self.assertEqual(values["ac_panel_requested_source"], "GENERATOR")

    def test_generator_command(self):
        self.assertEqual(self.values(0x02460B88, "01")["generator_command"], "START")
        self.assertEqual(self.values(0x02460B88, "02")["generator_command"], "STOP")

    def test_generator_status_enum(self):
        expected = {
            "00": "OFF_IDLE",
            "01": "RUNNING_SETTLED",
            "02": "STARTING",
            "03": "STARTING",
            "04": "STOPPING",
            "05": "STOPPING",
        }
        for payload, state in expected.items():
            with self.subTest(payload=payload):
                self.assertEqual(self.values(0x02440B88, payload)["generator_status"], state)

    def test_generator_frequency_signal(self):
        running = self.values(0x005A1020, "F401FFFFFFFFFFFF")
        stopped = self.values(0x005A1020, "0000FFFFFFFFFFFF")
        self.assertEqual(running["charger_candidate_1020_ac_frequency"], 50.0)
        self.assertEqual(running["generator_lifecycle_ac_signal"], "AC_PRESENT_50_HZ")
        self.assertEqual(stopped["generator_lifecycle_ac_signal"], "AC_ABSENT_0_HZ")

    def test_generator_lifecycle_sequence(self):
        frames = [
            self.frame(0x02460B88, "01", line=1, timestamp=1000.0),
            self.frame(0x02440B88, "02", line=2, timestamp=1000.1),
            self.frame(0x02440B88, "03", line=3, timestamp=1000.2),
            self.frame(0x005A1020, "F401FFFFFFFFFFFF", line=4, timestamp=1001.0),
            self.frame(0x02440B88, "01", line=5, timestamp=1001.5),
            self.frame(0x02460B88, "02", line=6, timestamp=1002.0),
            self.frame(0x02440B88, "05", line=7, timestamp=1002.1),
            self.frame(0x02440B88, "04", line=8, timestamp=1002.2),
            self.frame(0x005A1020, "0000FFFFFFFFFFFF", line=9, timestamp=1003.0),
            self.frame(0x02440B88, "00", line=10, timestamp=1003.5),
        ]
        events = mod.track_generator_lifecycle(frames, 1000.0)
        self.assertEqual(
            [event.state_after for event in events],
            [
                "STARTING",
                "STARTING",
                "STARTING",
                "RUNNING",
                "RUNNING_SETTLED",
                "STOPPING",
                "STOPPING",
                "STOPPING",
                "STOPPED",
                "OFF_IDLE",
            ],
        )
        self.assertTrue(all(event.accepted for event in events))

    def test_frequency_is_context_gated(self):
        tracker = mod.GeneratorLifecycleTracker()
        event = tracker.process(self.frame(0x005A1020, "0000FFFFFFFFFFFF"), 1000.0)[0]
        self.assertFalse(event.accepted)
        self.assertEqual(event.state_after, "UNKNOWN")
        self.assertEqual(event.signal, "AC_ABSENT_OUTSIDE_STOP_TRANSACTION")

    def test_starting_status_does_not_regress_running(self):
        tracker = mod.GeneratorLifecycleTracker()
        tracker.process(self.frame(0x02460B88, "01", timestamp=1000.0), 1000.0)
        tracker.process(self.frame(0x005A1020, "F401FFFFFFFFFFFF", timestamp=1001.0), 1000.0)
        event = tracker.process(self.frame(0x02440B88, "03", timestamp=1001.1), 1000.0)[0]
        self.assertEqual(event.state_before, "RUNNING")
        self.assertEqual(event.state_after, "RUNNING")
        self.assertEqual(event.signal, "STARTING_STATUS_LINGER")

    def test_ac(self):
        values = self.values(0x02040898, "00E60032")
        self.assertEqual(values["generator_or_ac_module_voltage"], 230)
        self.assertEqual(values["generator_or_ac_module_frequency"], 50)

    def test_house_battery(self):
        values = self.values(0x06020580, "35050A4E4800")
        self.assertEqual(values["house_battery_candidate_1_voltage"], 13.33)
        self.assertEqual(values["house_battery_candidate_1_current_code"], 10)
        self.assertEqual(values["house_battery_candidate_1_current_guess"], 1.0)
        self.assertEqual(values["house_battery_candidate_1_field3_raw"], 72)

    def test_charger_telemetry(self):
        values = self.values(0x00501008, "8700D1003809FFFF")
        self.assertEqual(values["charger_candidate_1008_dc_output_voltage_candidate"], 13.5)
        self.assertEqual(values["charger_candidate_1008_dc_output_current_candidate"], 20.9)
        self.assertEqual(values["charger_candidate_1008_ac_input_voltage_candidate"], 236.0)

    def test_charger_rating(self):
        values = self.values(0x00561020, "000006000C19FAFF")
        self.assertEqual(values["charger_candidate_1020_nominal_voltage_signature"], 12)
        self.assertEqual(values["charger_candidate_1020_rated_current_signature"], 25)

    def test_charger_frequency(self):
        values = self.values(0x005A1008, "F401FFFFFFFFFFFF")
        self.assertEqual(values["charger_candidate_1008_ac_frequency"], 50.0)


if __name__ == "__main__":
    unittest.main()
