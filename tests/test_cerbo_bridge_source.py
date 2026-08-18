import hashlib
import importlib.util
from pathlib import Path
import unittest


SOURCE_PAYLOAD_SHA256 = "d66c194a4753497dc6f6270e04cf615acc76ef3868efc8ffe522ea992725c208"


def load_assembler(root: Path):
    path = root / "cerbo" / "assemble_bridge.py"
    spec = importlib.util.spec_from_file_location("scheiber_bridge_assembler", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class TestCerboBridgeSource(unittest.TestCase):
    def test_payload_reconstructs_and_tank_unit_fix_compiles(self):
        root = Path(__file__).resolve().parents[1]
        assembler = load_assembler(root)

        source = assembler.decode_source_chunks(root / "cerbo")
        self.assertEqual(hashlib.sha256(source).hexdigest(), SOURCE_PAYLOAD_SHA256)

        patched = assembler.apply_source_patches(source)
        text = patched.decode("utf-8")

        self.assertEqual(text.count("capacity_l / 1000.0"), 2)
        self.assertIn('"capacity_m3":', text)
        self.assertIn('"remaining_m3":', text)
        self.assertNotIn('"capacity_l": svc["/Capacity"]', text)
        self.assertNotIn('"remaining_l": svc["/Remaining"]', text)

        compile(patched, "bridge.py", "exec")


if __name__ == "__main__":
    unittest.main()
