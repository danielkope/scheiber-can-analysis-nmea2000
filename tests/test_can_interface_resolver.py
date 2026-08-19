import importlib.util
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "cerbo" / "resolve_can_interface.py"
spec = importlib.util.spec_from_file_location("resolve_can_interface", MODULE_PATH)
resolver = importlib.util.module_from_spec(spec)
assert spec and spec.loader
sys.modules[spec.name] = resolver
spec.loader.exec_module(resolver)


class ResolverTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.net = self.root / "sys" / "class" / "net"
        self.net.mkdir(parents=True)
        self.drivers = self.root / "sys" / "drivers"
        self.drivers.mkdir(parents=True)
        self.devices = self.root / "sys" / "devices"
        self.devices.mkdir(parents=True)

    def tearDown(self):
        self.tmp.cleanup()

    def add_interface(
        self,
        name,
        driver,
        *,
        serial="",
        vendor="",
        product="",
        usb_path="3-1",
    ):
        driver_path = self.drivers / driver
        driver_path.mkdir(exist_ok=True)

        if vendor and product:
            usb_device = self.devices / usb_path
            usb_device.mkdir(parents=True, exist_ok=True)
            (usb_device / "idVendor").write_text(vendor)
            (usb_device / "idProduct").write_text(product)
            if serial:
                (usb_device / "serial").write_text(serial)
            device = usb_device / f"{usb_path}:1.0"
        else:
            device = self.devices / f"platform-{name}"
        device.mkdir(parents=True, exist_ok=True)
        (device / "driver").symlink_to(driver_path, target_is_directory=True)

        netdev = self.net / name
        netdev.mkdir()
        (netdev / "device").symlink_to(device, target_is_directory=True)

    def test_selects_unique_gs_usb_and_ignores_native_can(self):
        self.add_interface(
            "can0",
            "gs_usb",
            serial="0025003C5457530220383638",
            vendor="1d50",
            product="606f",
        )
        self.add_interface("can1", "sun4i_can")
        selected = resolver.resolve_candidate("auto", sys_class_net=self.net)
        self.assertEqual(selected.interface, "can0")
        self.assertEqual(selected.usb_serial, "0025003C5457530220383638")

    def test_matches_stable_usb_serial_when_can_number_changes(self):
        serial = "0025003C5457530220383638"
        self.add_interface(
            "can2",
            "gs_usb",
            serial=serial,
            vendor="1d50",
            product="606f",
        )
        self.add_interface(
            "can0",
            "gs_usb",
            serial="OTHER",
            vendor="1d50",
            product="606f",
            usb_path="3-2",
        )
        selected = resolver.resolve_candidate(
            "auto",
            usb_serial=serial,
            vendor_id="0x1D50",
            product_id="606F",
            sys_class_net=self.net,
        )
        self.assertEqual(selected.interface, "can2")

    def test_ambiguous_gs_usb_devices_fail_closed(self):
        self.add_interface("can0", "gs_usb", serial="A", vendor="1d50", product="606f")
        self.add_interface(
            "can2",
            "gs_usb",
            serial="B",
            vendor="1d50",
            product="606f",
            usb_path="3-2",
        )
        with self.assertRaises(resolver.ResolutionError):
            resolver.resolve_candidate("auto", sys_class_net=self.net)

    def test_explicit_native_interface_is_honoured(self):
        self.add_interface("can1", "sun4i_can")
        selected = resolver.resolve_candidate("can1", sys_class_net=self.net)
        self.assertEqual(selected.interface, "can1")
        self.assertEqual(selected.driver, "sun4i_can")

    def test_wrong_serial_fails_with_inventory(self):
        self.add_interface(
            "can0",
            "gs_usb",
            serial="RIGHT",
            vendor="1d50",
            product="606f",
        )
        with self.assertRaisesRegex(resolver.ResolutionError, "RIGHT"):
            resolver.resolve_candidate(
                "auto", usb_serial="WRONG", sys_class_net=self.net
            )


class ResolverPackagingTests(unittest.TestCase):
    def test_resolver_and_runit_sources_validate(self):
        subprocess.run(
            [sys.executable, "-m", "py_compile", str(MODULE_PATH)],
            check=True,
        )
        for path in (
            ROOT / "cerbo" / "install.sh",
            ROOT / "cerbo" / "service" / "run",
            ROOT / "cerbo" / "service-switch" / "run",
        ):
            subprocess.run(["sh", "-n", str(path)], check=True)

    def test_installer_persists_stable_usb_identity(self):
        source = (ROOT / "cerbo" / "install.sh").read_text(encoding="utf-8")
        self.assertIn('CAN_IF="${CAN_IF:-auto}"', source)
        self.assertIn("resolve_can_interface.py", source)
        self.assertIn("CAN_USB_SERIAL", source)
        self.assertIn("CAN_USB_VENDOR_ID", source)
        self.assertIn("CAN_USB_PRODUCT_ID", source)

    def test_services_share_one_runtime_interface_selection(self):
        main_run = (ROOT / "cerbo" / "service" / "run").read_text(encoding="utf-8")
        switch_run = (ROOT / "cerbo" / "service-switch" / "run").read_text(encoding="utf-8")
        self.assertIn("resolve_can_interface.py", main_run)
        self.assertIn("/run/scheiber-can-if", main_run)
        self.assertIn("/run/scheiber-can-if", switch_run)
        self.assertIn("single owner", switch_run)


if __name__ == "__main__":
    unittest.main()
