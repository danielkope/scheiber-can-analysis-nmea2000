from pathlib import Path
import subprocess
import unittest


ROOT = Path(__file__).resolve().parents[1]
INSTALLER = ROOT / "cerbo" / "install.sh"


class RcLocalPersistenceTests(unittest.TestCase):
    def test_installer_parses_as_posix_shell(self):
        subprocess.run(["sh", "-n", str(INSTALLER)], check=True)

    def test_service_block_is_inserted_before_exit_zero(self):
        source = INSTALLER.read_text(encoding="utf-8")
        self.assertIn('RC_LOCAL="${RC_LOCAL:-/data/rc.local}"', source)
        self.assertIn("Older revisions appended the block after `exit 0`", source)
        self.assertIn(
            r"!inserted && $0 ~ /^[[:space:]]*exit[[:space:]]+0[[:space:]]*$/",
            source,
        )
        self.assertIn("print main_marker", source)
        self.assertIn("print switch_marker", source)
        self.assertIn("$0 == main_marker || $0 == switch_marker", source)

    def test_venus_service_control_uses_svc_not_sv(self):
        source = INSTALLER.read_text(encoding="utf-8")
        self.assertIn("command -v svc", source)
        self.assertIn("/command/svc", source)
        self.assertIn('"$SVC" -u "$SERVICE_LINK"', source)
        self.assertNotIn("sv status", source)


if __name__ == "__main__":
    unittest.main()
