import hashlib
from pathlib import Path
import unittest


EXPECTED_SHA256 = "e93273e858fa87d4e7be16b0068e3ebaab15aa531a5a720d04caf7c9fcc29190"


class TestCerboBridgeSource(unittest.TestCase):
    def test_canonical_bridge_compiles_and_has_correct_tank_units(self):
        root = Path(__file__).resolve().parents[1]
        path = root / "cerbo" / "bridge.py"
        source = path.read_bytes()
        text = source.decode("utf-8")

        self.assertEqual(hashlib.sha256(source).hexdigest(), EXPECTED_SHA256)
        self.assertIn('BRIDGE_VERSION = "5.5.0"', text)
        self.assertIn('None if capacity_l is None else float(capacity_l) / 1000.0', text)
        self.assertIn('"capacity_m3": svc["/Capacity"]', text)
        self.assertIn('"remaining_m3": svc["/Remaining"]', text)
        self.assertNotIn('"capacity_l": svc["/Capacity"]', text)
        self.assertNotIn('"remaining_l": svc["/Remaining"]', text)
        compile(source, "bridge.py", "exec")


if __name__ == "__main__":
    unittest.main()
