import hashlib
import importlib.util
from pathlib import Path
import unittest


SOURCE_PAYLOAD_SHA256 = "c4b6f4615b0a388e63c3aec315979154f9b7aed44a18d8e226b36877b8dd3ee3"


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
        cerbo = root / "cerbo"
        assembler = load_assembler(root)

        # Each source part is independently base64-encoded and may have its own
        # padding. The assembler must decode parts separately before joining the
        # decoded bytes; joining the encoded strings first fails on Python 3.12.
        source = assembler.decode_source_chunks(cerbo)
        self.assertEqual(hashlib.sha256(source).hexdigest(), SOURCE_PAYLOAD_SHA256)

        patched = assembler.apply_source_patches(source)
        text = patched.decode("utf-8")

        # The human-facing configuration remains litres, but the two Victron
        # tank D-Bus publication/calculation sites must convert to cubic metres.
        self.assertEqual(text.count("capacity_l / 1000.0"), 2)
        self.assertIn('"capacity_m3":', text)
        self.assertIn('"remaining_m3":', text)
        self.assertNotIn('"capacity_l": svc["/Capacity"]', text)
        self.assertNotIn('"remaining_l": svc["/Remaining"]', text)

        compile(patched, "bridge.py", "exec")


if __name__ == "__main__":
    unittest.main()
