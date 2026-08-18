#!/usr/bin/env python3
"""Reconstruct the reviewed bridge.py and apply repository-maintained fixes.

The large field-tested source is kept as an immutable base64 payload. Small,
reviewable corrections discovered after field validation are applied here so
that the original source provenance remains verifiable.
"""

import argparse
import base64
import hashlib
import re
from pathlib import Path

# SHA-256 of the reviewed v5.4.1 repository payload before post-validation fixes.
SOURCE_PAYLOAD_SHA256 = "c4b6f4615b0a388e63c3aec315979154f9b7aed44a18d8e226b36877b8dd3ee3"


def apply_source_patches(data: bytes) -> bytes:
    """Apply deterministic post-validation fixes to the reviewed source.

    Tank capacities are configured in litres for human readability, but the
    Victron tank D-Bus contract uses cubic metres for /Capacity and /Remaining.
    The field-tested v5.4.1 source published the litre values directly, making
    Signal K display 600 m3 instead of 0.600 m3. Keep the configuration in
    litres and convert only at the D-Bus publication points.
    """
    text = data.decode("utf-8")
    lines = text.splitlines(keepends=True)

    capacity_patches = 0
    remaining_patches = 0
    patched = []

    for line in lines:
        # Patch only executable tank publication/calculation lines. Do not
        # rewrite the status-JSON key named "capacity_l".
        if (
            ("/Capacity" in line)
            and re.search(r"\bcapacity_l\b", line)
            and '"capacity_l"' not in line
            and "'capacity_l'" not in line
        ):
            line, count = re.subn(
                r"\bcapacity_l\b", "(capacity_l / 1000.0)", line, count=1
            )
            capacity_patches += count

        # Same for /Remaining: preserve the level-percent calculation, but
        # make its capacity factor cubic metres instead of litres.
        if (
            ("/Remaining" in line)
            and re.search(r"\bcapacity_l\b", line)
            and '"remaining_l"' not in line
            and "'remaining_l'" not in line
        ):
            line, count = re.subn(
                r"\bcapacity_l\b", "(capacity_l / 1000.0)", line, count=1
            )
            remaining_patches += count

        patched.append(line)

    text = "".join(patched)

    # The status snapshot follows the actual D-Bus units after this fix.
    text, status_capacity = re.subn(
        r'"capacity_l"\s*:', '"capacity_m3":', text, count=1
    )
    text, status_remaining = re.subn(
        r'"remaining_l"\s*:', '"remaining_m3":', text, count=1
    )

    if capacity_patches != 1:
        raise RuntimeError(
            f"expected exactly one tank /Capacity conversion patch, got {capacity_patches}"
        )
    if remaining_patches != 1:
        raise RuntimeError(
            f"expected exactly one tank /Remaining conversion patch, got {remaining_patches}"
        )
    if status_capacity != 1 or status_remaining != 1:
        raise RuntimeError(
            "expected exactly one status JSON tank-unit key replacement for each field"
        )

    patched_bytes = text.encode("utf-8")
    compile(patched_bytes, "bridge.py", "exec")
    return patched_bytes


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("-o", "--output", default="bridge.py")
    args = parser.parse_args()

    root = Path(__file__).resolve().parent
    encoded = "".join(
        (root / "source" / name).read_text(encoding="ascii").strip()
        for name in ("bridge.py.part1", "bridge.py.part2")
    )
    source = base64.b64decode(encoded, validate=True)
    source_digest = hashlib.sha256(source).hexdigest()
    if source_digest != SOURCE_PAYLOAD_SHA256:
        raise SystemExit(
            f"source SHA-256 mismatch: expected {SOURCE_PAYLOAD_SHA256}, got {source_digest}"
        )

    data = apply_source_patches(source)
    digest = hashlib.sha256(data).hexdigest()

    output = Path(args.output)
    output.write_bytes(data)
    print(
        f"wrote {output} ({len(data)} bytes), source SHA-256 {source_digest}, "
        f"installed SHA-256 {digest}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
