import hashlib
from pathlib import Path
import unittest


EXPECTED_SHA256 = "f3fecabfb42530c2fc9dc3007fbd0036092a33e4e10a57adc2242a0efd45f3bc"


class TestCerboBridgeSource(unittest.TestCase):
    def test_canonical_source_hash(self):
        source_path = Path(__file__).resolve().parent.parent / "cerbo" / "bridge.py"
        actual_sha256 = hashlib.sha256(source_path.read_bytes()).hexdigest()
        self.assertEqual(
            actual_sha256,
            EXPECTED_SHA256,
            "cerbo/bridge.py does not match pinned production SHA-256",
        )

    def test_canonical_source_version(self):
        source_path = Path(__file__).resolve().parent.parent / "cerbo" / "bridge.py"
        content = source_path.read_text(encoding="utf-8")
        self.assertIn('BRIDGE_VERSION = "5.9.0"', content)
        self.assertIn('None if capacity_l is None else float(capacity_l) / 1000.0', content)
        self.assertIn('"capacity_m3": svc["/Capacity"]', content)
        self.assertIn('"remaining_m3": svc["/Remaining"]', content)
        self.assertNotIn('"capacity_l": svc["/Capacity"]', content)
        self.assertNotIn('"remaining_l": svc["/Remaining"]', content)
        self.assertIn('STARTER_LOW_VOLTAGE_WARN = 12.2', content)
        self.assertIn('STARTER_LOW_VOLTAGE_ALARM = 11.8', content)
        self.assertIn('STARTER_VOLTAGE_HYSTERESIS = 0.3', content)
        self.assertIn('STARTER_ALARM_HOLD_SECONDS = 15.0', content)
        self.assertIn('/StarterVoltageAlarm', content)
        self.assertIn('update_smart_starter_battery_alarm', content)
        compile(content, "bridge.py", "exec")


if __name__ == "__main__":
    unittest.main()
