#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Resolve the current Linux CAN netdev for the Scheiber USB-CAN adapter.

Linux may enumerate the same gs_usb adapter as can0, can1, can2, ... on
successive boots. This helper selects the physical adapter by stable USB
identity and returns its current network-interface name.

Resolution policy:

* An explicit interface name is honoured, with optional USB identity checks.
* ``auto`` considers only interfaces backed by the configured driver
  (``gs_usb`` by default).
* A configured USB serial number is an exact match and takes priority.
* Vendor/product IDs can further constrain selection.
* Without identity filters, exactly one matching driver is required.
* Ambiguity is an error; the resolver never chooses the first ``canN``.
"""

from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
import json
import os
from pathlib import Path
import sys
from typing import Iterable, Optional, Sequence


@dataclass(frozen=True)
class CanCandidate:
    interface: str
    driver: str
    device_path: str
    usb_path: str = ""
    usb_serial: str = ""
    vendor_id: str = ""
    product_id: str = ""

    def summary(self) -> str:
        usb_id = (
            f"{self.vendor_id}:{self.product_id}"
            if self.vendor_id or self.product_id
            else "-"
        )
        return (
            f"{self.interface}: driver={self.driver or '-'} "
            f"usb={usb_id} serial={self.usb_serial or '-'} "
            f"path={self.usb_path or self.device_path}"
        )


class ResolutionError(RuntimeError):
    """Raised when a CAN interface cannot be selected safely."""


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace").strip()
    except (FileNotFoundError, OSError):
        return ""


def _normalize_usb_id(value: str) -> str:
    normalized = str(value or "").strip().lower()
    if normalized.startswith("0x"):
        normalized = normalized[2:]
    return normalized


def _driver_name(device: Path) -> str:
    driver_link = device / "driver"
    try:
        return driver_link.resolve(strict=True).name
    except (FileNotFoundError, OSError):
        return ""


def _usb_identity(device: Path) -> tuple[str, str, str, str]:
    """Return serial, vendor, product and USB-device path for a netdev device."""

    nodes: Iterable[Path] = (device, *device.parents)
    for node in nodes:
        vendor = _normalize_usb_id(_read_text(node / "idVendor"))
        product = _normalize_usb_id(_read_text(node / "idProduct"))
        if vendor and product:
            return (
                _read_text(node / "serial"),
                vendor,
                product,
                str(node),
            )
    return "", "", "", ""


def enumerate_candidates(sys_class_net: Path = Path("/sys/class/net")) -> list[CanCandidate]:
    candidates: list[CanCandidate] = []
    try:
        entries = sorted(sys_class_net.iterdir(), key=lambda item: item.name)
    except (FileNotFoundError, OSError) as exc:
        raise ResolutionError(f"cannot inspect {sys_class_net}: {exc}") from exc

    for entry in entries:
        device_link = entry / "device"
        try:
            device = device_link.resolve(strict=True)
        except (FileNotFoundError, OSError):
            continue

        driver = _driver_name(device)
        # Ignore ordinary Ethernet/Wi-Fi interfaces. CAN interfaces expose a
        # CAN driver or use a can*/slcan* style name. The auto path later
        # applies the stricter gs_usb filter.
        if "can" not in driver.lower() and not (
            entry.name.startswith("can") or entry.name.startswith("slcan")
        ):
            continue

        serial, vendor, product, usb_path = _usb_identity(device)
        candidates.append(
            CanCandidate(
                interface=entry.name,
                driver=driver,
                device_path=str(device),
                usb_path=usb_path,
                usb_serial=serial,
                vendor_id=vendor,
                product_id=product,
            )
        )
    return candidates


def resolve_candidate(
    interface: str = "auto",
    *,
    usb_serial: str = "",
    vendor_id: str = "",
    product_id: str = "",
    driver: str = "gs_usb",
    sys_class_net: Path = Path("/sys/class/net"),
) -> CanCandidate:
    candidates = enumerate_candidates(sys_class_net)
    requested = str(interface or "auto").strip()
    serial_filter = str(usb_serial or "").strip()
    vendor_filter = _normalize_usb_id(vendor_id)
    product_filter = _normalize_usb_id(product_id)

    if requested.lower() != "auto":
        matches = [item for item in candidates if item.interface == requested]
        if not matches:
            raise ResolutionError(f"explicit CAN interface {requested!r} does not exist")
    else:
        matches = [item for item in candidates if item.driver == driver]

    if serial_filter:
        matches = [item for item in matches if item.usb_serial == serial_filter]
    if vendor_filter:
        matches = [item for item in matches if item.vendor_id == vendor_filter]
    if product_filter:
        matches = [item for item in matches if item.product_id == product_filter]

    if len(matches) == 1:
        return matches[0]

    selector = [f"interface={requested}", f"driver={driver}"]
    if serial_filter:
        selector.append(f"serial={serial_filter}")
    if vendor_filter or product_filter:
        selector.append(f"usb={vendor_filter or '*'}:{product_filter or '*'}")

    if not matches:
        reason = "no CAN interface matched " + ", ".join(selector)
    else:
        reason = (
            f"{len(matches)} CAN interfaces matched "
            + ", ".join(selector)
            + "; refusing to guess"
        )

    available = "\n".join(f"  {item.summary()}" for item in candidates)
    if not available:
        available = "  (no CAN-like interfaces found)"
    raise ResolutionError(f"{reason}\navailable interfaces:\n{available}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--interface",
        default=os.environ.get("CAN_IF", "auto"),
        help="explicit netdev name or 'auto' (default: environment CAN_IF or auto)",
    )
    parser.add_argument(
        "--usb-serial",
        default=os.environ.get("CAN_USB_SERIAL", ""),
        help="exact USB serial number",
    )
    parser.add_argument(
        "--vendor-id",
        default=os.environ.get("CAN_USB_VENDOR_ID", ""),
        help="optional USB vendor ID, with or without 0x prefix",
    )
    parser.add_argument(
        "--product-id",
        default=os.environ.get("CAN_USB_PRODUCT_ID", ""),
        help="optional USB product ID, with or without 0x prefix",
    )
    parser.add_argument(
        "--driver",
        default=os.environ.get("CAN_DRIVER", "gs_usb"),
        help="driver used for auto discovery (default: gs_usb)",
    )
    parser.add_argument(
        "--sys-class-net",
        type=Path,
        default=Path(os.environ.get("CAN_SYS_CLASS_NET", "/sys/class/net")),
        help=argparse.SUPPRESS,
    )
    parser.add_argument(
        "--field",
        choices=("interface", "serial", "vendor", "product", "json", "summary"),
        default="interface",
        help="selected value to print",
    )
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        candidate = resolve_candidate(
            args.interface,
            usb_serial=args.usb_serial,
            vendor_id=args.vendor_id,
            product_id=args.product_id,
            driver=args.driver,
            sys_class_net=args.sys_class_net,
        )
    except ResolutionError as exc:
        print(f"scheiber CAN resolver: {exc}", file=sys.stderr)
        return 2

    values = {
        "interface": candidate.interface,
        "serial": candidate.usb_serial,
        "vendor": candidate.vendor_id,
        "product": candidate.product_id,
        "json": json.dumps(asdict(candidate), sort_keys=True),
        "summary": candidate.summary(),
    }
    print(values[args.field])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
