# Cerbo GX bridge package

This directory contains the optional active Victron integration. The passive analyzer elsewhere in the repository remains read-only.

## Reconstructing the reviewed source

The field-tested v5.4.1 Python source is stored as two **independently base64-encoded** payload chunks:

```text
source/bridge.py.part1
source/bridge.py.part2
```

Decode each chunk independently and concatenate the decoded bytes. The SHA-256 of that immutable decoded repository payload is:

```text
d66c194a4753497dc6f6270e04cf615acc76ef3868efc8ffe522ea992725c208
```

`assemble_bridge.py` verifies that payload and then applies small, explicit post-validation corrections before installation. The first such correction fixes Victron tank units: configured vessel capacities remain human-readable litres, while D-Bus `/Capacity` and `/Remaining` are published in cubic metres as required by Victron/Signal K.

Reconstruct the installable bridge in any checkout with:

```bash
cd cerbo
python3 assemble_bridge.py -o bridge.py
python3 -m py_compile bridge.py
sha256sum bridge.py
```

The assembler prints both the immutable source-payload SHA and the final installed-file SHA. It fails closed if the expected tank-unit patch sites are not found exactly once.

The earlier pre-documentation-reconciliation field-tested v5.4.1 file had SHA-256 `b7acb294467147a50166ac1468fe64de37c8a0facca920f3d0e8f2f89ee5a5c1`. Generator/CAN control semantics remain unchanged by the tank-unit correction.

## Tank D-Bus units

Vessel capacities are configured as:

```text
Fresh water:   600 L
Diesel tank 1: 500 L
Diesel tank 2: 500 L
```

Victron D-Bus and Signal K expect volume in cubic metres, so the installed bridge publishes:

```text
/Capacity   0.600, 0.500, 0.500 m3
/Remaining  capacity_m3 * level_percent / 100
/Level      percent
```

For example, fresh water at 74% is `/Capacity=0.600` and `/Remaining=0.444`.

## Install on a Cerbo GX

As root, after the PR is merged:

```bash
mkdir -p /data/scheiber-gx-installer
cd /data/scheiber-gx-installer
wget -O install.sh https://raw.githubusercontent.com/danielkope/scheiber-can-analysis-nmea2000/main/cerbo/install.sh
chmod +x install.sh
CAN_IF=can2 CAN_BITRATE=250000 ./install.sh
```

To test the open fix branch before merge, point both the downloaded installer and `RAW_BASE` at the branch:

```bash
BRANCH=fix/tank-dbus-units
BASE="https://raw.githubusercontent.com/danielkope/scheiber-can-analysis-nmea2000/$BRANCH/cerbo"
wget -O install.sh "$BASE/install.sh"
chmod +x install.sh
RAW_BASE="$BASE" CAN_IF=can2 CAN_BITRATE=250000 ./install.sh
```

`install.sh` downloads the two payload chunks and `assemble_bridge.py`, verifies and patches the source, compiles it, installs the runit wrapper, persists the `/service/scheiber-gx` link through `/data/rc.local`, and starts the service with `svc`.

After restart, verify the corrected tank units:

```bash
for s in \
  com.victronenergy.tank.scheiber_fresh \
  com.victronenergy.tank.scheiber_diesel1 \
  com.victronenergy.tank.scheiber_diesel2
do
  echo "===== $s ====="
  for p in Level Capacity Remaining; do
    printf '%-12s ' "$p:"
    dbus -y "$s" "/$p" GetValue
  done
done
```

Read [`../docs/CERBO_GX_INTEGRATION.md`](../docs/CERBO_GX_INTEGRATION.md) before installation. It covers wiring, explicit SmartShunt/system-battery selection, D-Bus checks, timed-run validation, rollback, and the current post-stop `OFF_IDLE` restart caveat.
