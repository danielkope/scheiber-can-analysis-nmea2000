# Cerbo GX bridge package

This directory contains the optional active Victron integration. The passive analyzer elsewhere in the repository remains read-only.

## Reconstructing the reviewed source

The reviewed v5.4.1 Python source is stored as two base64 payload chunks:

```text
source/bridge.py.part1
source/bridge.py.part2
```

This keeps the large field-tested source payload deterministic while allowing the installer to verify the exact reconstructed file before execution.

Reconstruct it in any checkout with:

```bash
cd cerbo
python3 assemble_bridge.py -o bridge.py
python3 -m py_compile bridge.py
sha256sum bridge.py
```

Expected assembled SHA-256:

```text
c4b6f4615b0a388e63c3aec315979154f9b7aed44a18d8e226b36877b8dd3ee3
```

The pre-documentation-reconciliation field-tested v5.4.1 file had SHA-256 `b7acb294467147a50166ac1468fe64de37c8a0facca920f3d0e8f2f89ee5a5c1`; executable Python statements are unchanged.

## Install on a Cerbo GX

As root:

```bash
mkdir -p /data/scheiber-gx-installer
cd /data/scheiber-gx-installer
wget -O install.sh https://raw.githubusercontent.com/danielkope/scheiber-can-analysis-nmea2000/main/cerbo/install.sh
chmod +x install.sh
CAN_IF=can2 CAN_BITRATE=250000 ./install.sh
```

`install.sh` downloads the two payload chunks, reconstructs `/data/scheiber-gx/bridge.py`, verifies the SHA-256 above, installs the runit wrapper, persists the `/service/scheiber-gx` link through `/data/rc.local`, and starts the service with `svc`.

Read [`../docs/CERBO_GX_INTEGRATION.md`](../docs/CERBO_GX_INTEGRATION.md) before installation. It covers wiring, explicit SmartShunt/system-battery selection, D-Bus checks, timed-run validation, rollback, and the current post-stop `OFF_IDLE` restart caveat.
