import base64
import hashlib
from pathlib import Path
import unittest


EXPECTED_SHA256 = "c4b6f4615b0a388e63c3aec315979154f9b7aed44a18d8e226b36877b8dd3ee3"


class TestCerboBridgeSource(unittest.TestCase):
    def test_payload_reconstructs_reviewed_bridge_and_compiles(self):
        root = Path(__file__).resolve().parents[1] / "cerbo"
        encoded = "".join(
            (root / "source" / name).read_text(encoding="ascii").strip()
            for name in ("bridge.py.part1", "bridge.py.part2")
        )
        source = base64.b64decode(encoded, validate=True)
        self.assertEqual(hashlib.sha256(source).hexdigest(), EXPECTED_SHA256)
        compile(source, "bridge.py", "exec")


if __name__ == "__main__":
    unittest.main()
