#!/usr/bin/env python3
"""Reconstruct the reviewed bridge.py from the repository payload chunks."""

import argparse
import base64
import hashlib
from pathlib import Path

EXPECTED_SHA256 = "c4b6f4615b0a388e63c3aec315979154f9b7aed44a18d8e226b36877b8dd3ee3"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("-o", "--output", default="bridge.py")
    args = parser.parse_args()

    root = Path(__file__).resolve().parent
    encoded = "".join(
        (root / "source" / name).read_text(encoding="ascii").strip()
        for name in ("bridge.py.part1", "bridge.py.part2")
    )
    data = base64.b64decode(encoded, validate=True)
    digest = hashlib.sha256(data).hexdigest()
    if digest != EXPECTED_SHA256:
        raise SystemExit(f"SHA-256 mismatch: expected {EXPECTED_SHA256}, got {digest}")

    output = Path(args.output)
    output.write_bytes(data)
    print(f"wrote {output} ({len(data)} bytes), SHA-256 {digest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
