from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
BRIDGE = (ROOT / "cerbo" / "switch_bridge.py").read_text(encoding="utf-8")
PROTOCOL = (ROOT / "cerbo" / "switch_protocol.py").read_text(encoding="utf-8")


class SwitchBridgeSourceTests(unittest.TestCase):
    def test_direct_output_command_is_not_operationalized(self):
        # CMD_S_TOR candidate 0x02361808 must not appear in runtime source.
        self.assertNotIn("0x02361808", BRIDGE)
        self.assertNotIn("0x02361808", PROTOCOL)

    def test_panel_key_command_is_used(self):
        self.assertIn("SWITCH_ID = 0x04001808", PROTOCOL)
        self.assertIn("build_key_frames", BRIDGE)

    def test_unknown_state_gate_is_present(self):
        self.assertIn("physical state is UNKNOWN", BRIDGE)
        self.assertIn("channel_synchronized", BRIDGE)

    def test_no_retry_policy_is_explicit(self):
        self.assertIn("no retry sent", BRIDGE)
        self.assertNotIn("retry_current_action", BRIDGE)

    def test_running_feedback_is_separate(self):
        self.assertIn('"/Scheiber/Running"', BRIDGE)
        self.assertIn("DIGITAL_INPUT_ID", PROTOCOL)

    def test_node_red_auto_target_hook_exists(self):
        self.assertIn('"/Scheiber/AutoState"', BRIDGE)
        self.assertIn("channel is not in AUTO", BRIDGE)

    def test_installer_pinned_hashes_match_sources(self):
        import hashlib
        import re
        installer = (ROOT / "cerbo" / "install_switches.sh").read_text(encoding="utf-8")
        expected = {
            "BRIDGE": hashlib.sha256((ROOT / "cerbo" / "switch_bridge.py").read_bytes()).hexdigest(),
            "PROTOCOL": hashlib.sha256((ROOT / "cerbo" / "switch_protocol.py").read_bytes()).hexdigest(),
            "RUN": hashlib.sha256((ROOT / "cerbo" / "switch-service" / "run").read_bytes()).hexdigest(),
        }
        for name, digest in expected.items():
            m = re.search(r'EXPECTED_%s_SHA256="([0-9a-f]{64})"' % name, installer)
            self.assertIsNotNone(m)
            self.assertEqual(m.group(1), digest)


if __name__ == "__main__":
    unittest.main()
