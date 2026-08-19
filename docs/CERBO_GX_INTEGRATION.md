# Victron Cerbo GX integration

This document describes the tested Scheiber CAN integration for a Victron Cerbo GX using a DSD TECH SH-C30A USB-CAN adapter (`gs_usb`). The passive analyzer elsewhere in the repository remains read-only; the optional Cerbo bridge can transmit only the two generator commands that were live-validated on this installation.

## Current tested bridge

Tested environment:

```text
Victron Cerbo GX
Venus OS v3.75 (20260624163305 v3.75)
Linux 6.12.90-venus-2, armv7l
DSD TECH SH-C30A via gs_usb
Scheiber CAN can2 @ 250000 bit/s
29-bit extended CAN identifiers
```

Canonical runtime source:

```text
cerbo/bridge.py
version 5.8.0
SHA-256 e0a6deb23a8d94c696386436991b068f187addd184c475b3370bf5960170e821
```

The bridge publishes:

```text
com.victronenergy.genset.scheiber
com.victronenergy.grid.scheiber_shore
com.victronenergy.inverter.scheiber_mastervolt
```

Victron `dbus-generator` creates the normal connected-genset manager, typically:

```text
com.victronenergy.generator.startstop1
```

The bridge also publishes three native Victron tank services, native MasterVolt 2000W Inverter and Shore Power services, native switch outputs (`com.victronenergy.switch.scheiber`), and, when the GX system battery is explicitly selected, six house-battery services plus two experimental engine-battery services and the generator starter battery.

## Safety boundary

The following generator commands were tested live on this installation:

```text
02460B88#01   START
02460B88#02   STOP
```

The bridge sends each accepted command once and deliberately does **not** implement automatic CAN retries.

The bridge does **not** transmit AC/House source-selector requests. In particular, it never sends:

```text
0x02420B90
0x02420B88
```

Those IDs are documented only for protocol analysis. Live validation on one vessel is not an OEM protocol guarantee; preserve the existing generator and marine-electrical safety systems.

## Wiring

Scheiber six-pin connector to SH-C30A:

| Scheiber pin | Function | SH-C30A |
|---:|---|---|
| 5 | CAN-H | CAN_H |
| 6 | CAN-L | CAN_L |
| 2 or installation-specific 3 | GND | GND |
| 1 | Recovery | leave open |
| 4 | +12 V | **never connect to SH-C30A** |

The SH-C30A is USB powered. On an existing correctly terminated Scheiber bus, leave its 120-ohm termination **OFF**. With vessel power off, approximately 60 ohms between CAN-H and CAN-L normally indicates two 120-ohm end terminators.

## Venus OS prerequisites

The tested Venus image already provided the required runtime tools:

```text
python3
dbus
Victron velib_python / vedbus.py
ip
candump
cansend
svc
```

Confirm the USB-CAN interface before installation:

```bash
lsusb
lsmod | grep -E 'gs_usb|can'
ip -details link show
```

The tested adapter enumerated as `can2`.

## Required GX configuration

### Explicitly select the existing system battery

The bridge refuses to register its extra `com.victronenergy.battery.*` services while the GX system-battery selection is `default`. This prevents a Scheiber per-battery service from displacing the existing SmartShunt as the system battery.

Check:

```bash
dbus -y com.victronenergy.settings \
  /Settings/SystemSetup/BatteryService GetValue
```

If it returns `default`, select the existing SmartShunt/system battery explicitly in Venus OS, then restart the bridge. Generator and tank integration do not depend on the additional battery services.

### AC input roles

For the tested installation:

```text
AC input 1 = Shore power
AC input 2 = Generator
```

Observed settings:

```text
/Settings/SystemSetup/AcInput1 = 3
/Settings/SystemSetup/AcInput2 = 2
```

The bridge reads these settings for diagnostics only and does not rewrite them.

## Installation

### Install from GitHub

After the relevant changes are merged to `main`:

```bash
mkdir -p /data/scheiber-gx-installer
cd /data/scheiber-gx-installer

wget -O install.sh \
  https://raw.githubusercontent.com/danielkope/scheiber-can-analysis-nmea2000/main/cerbo/install.sh
chmod +x install.sh

CAN_IF=can2 CAN_BITRATE=250000 ./install.sh
```

To test an open branch before merge:

```bash
BRANCH=fix/tank-dbus-units
BASE="https://raw.githubusercontent.com/danielkope/scheiber-can-analysis-nmea2000/$BRANCH/cerbo"

wget -O install.sh "$BASE/install.sh"
chmod +x install.sh
RAW_BASE="$BASE" CAN_IF=can2 CAN_BITRATE=250000 ./install.sh
```

The installer performs this sequence:

1. downloads the complete canonical `cerbo/bridge.py` to a temporary path;
2. compiles it with `python3 -m py_compile`;
3. verifies its pinned SHA-256;
4. downloads the runit `service/run` wrapper;
5. backs up the currently installed script as `/data/scheiber-gx/bridge.py.previous`;
6. replaces `/data/scheiber-gx/bridge.py` with the complete verified script;
7. installs the runit wrapper;
8. persists `/service/scheiber-gx -> /data/scheiber-gx/service` through `/data/rc.local`;
9. restarts the service with `svc`.

A failed download, compile, or checksum happens before the installed bridge is replaced.

### Install from a checked-out repository

```bash
cd /path/to/scheiber-can-analysis-nmea2000
CAN_IF=can2 CAN_BITRATE=250000 ./cerbo/install.sh
```

When local `cerbo/bridge.py` and `cerbo/service/run` exist, the installer uses those files directly.

## Installed files

```text
/data/scheiber-gx/bridge.py
/data/scheiber-gx/bridge.py.previous
/data/scheiber-gx/service/run
/data/scheiber-gx/bridge.log
/data/scheiber-gx/status.json
/service/scheiber-gx -> /data/scheiber-gx/service
```

The persistent runtime files live under `/data`.

## First verification

### SocketCAN

```bash
ip -details -statistics link show can2
```

Expected essentials:

- bitrate `250000`;
- interface `UP`;
- no rapidly increasing RX/TX errors;
- no repeated bus-off events.

Passive traffic check:

```bash
candump -L can2
```

### Bridge process

```bash
tail -n 100 /data/scheiber-gx/bridge.log
cat /data/scheiber-gx/status.json
sha256sum /data/scheiber-gx/bridge.py
```

Expected installed SHA for bridge 5.4.2:

```text
6c25ce4b095385217564fc6bf6fdc843dfefd835993d643843811e7f0f737097
```

Useful service commands:

```bash
svc -d /service/scheiber-gx   # stop
svc -u /service/scheiber-gx   # start
svc -t /service/scheiber-gx   # restart
```

Use `svc`; `sv` was not installed on the tested image.

### Connected-genset D-Bus service

```bash
for p in ProductName Connected RemoteStartModeEnabled Start StatusCode; do
    printf '%-28s ' "$p:"
    dbus -y com.victronenergy.genset.scheiber /$p GetValue
done
```

Typical healthy stopped state:

```text
ProductName:                 'Scheiber Generator'
Connected:                   1
RemoteStartModeEnabled:      1
Start:                       0
StatusCode:                  0
```

Confirm Victron matched the genset:

```bash
for p in Enabled GensetService GensetServiceType GensetInstance \
         State ManualStart ManualStartTimer RunningByCondition \
         RunningByConditionCode Runtime; do
    printf '%-28s ' "$p:"
    dbus -y com.victronenergy.generator.startstop1 /$p GetValue
done
```

`GensetService` should be `com.victronenergy.genset.scheiber` and `Enabled` should be `1`.

## Generator-control architecture

The ownership rule is fundamental:

- `com.victronenergy.genset.scheiber /Start` is **Victron command state**;
- Scheiber CAN feedback never writes `/Start` locally;
- `/StatusCode` is **physical generator feedback**;
- a physical/external Scheiber START is adopted into Victron by setting manager `/ManualStart=1`;
- when Victron then synchronizes `/Start=1`, the bridge suppresses duplicate CAN START;
- a physical STOP clears `/ManualStart` only when manual ownership is active;
- automatic Victron start conditions are not silently disabled.

Victron status mapping:

| Physical state | `/StatusCode` |
|---|---:|
| stopped / idle | 0 |
| STARTING | 1 |
| RUNNING / RUNNING_SETTLED | 8 |
| STOPPING | 9 |

## Confirmed generator CAN mapping

### Command `0x02460B88`

| Payload | Meaning | Status |
|---|---|---|
| `01` | START | live transmit confirmed |
| `02` | STOP | live transmit confirmed |

Direct low-level diagnostics only:

```bash
cansend can2 02460B88#01
cansend can2 02460B88#02
```

Normal operation should use the Victron generator UI or D-Bus manager.

### Lifecycle `0x02440B88`

| Payload | Interpretation |
|---|---|
| `00` | OFF_IDLE |
| `01` | RUNNING_SETTLED |
| `02`, `03` | STARTING |
| `04`, `05` | STOPPING |
| `06`, `07` | abort/error candidates; unresolved |

### Generator frequency `0x005A1020`

Bytes 0-1 are `uint16` little-endian x0.1 Hz:

```text
F4 01 -> 500 -> 50.0 Hz
90 01 -> 400 -> 40.0 Hz
00 00 -> 0.0 Hz
```

Live testing established that this signal is generator-specific. With the generator off and shore power present, `0x005A1020` remained 0 Hz while shared `0x02040898` still reported approximately 235 V / 50 Hz.

The bridge requires 47-53 Hz plus a 3 s confirmation hold before declaring RUNNING. A 0 Hz generator-specific sample confirms physical STOPPED.

## Post-stop restart caveat

Scheiber has two useful stopped milestones:

1. `005A1020 = 0.0 Hz` -> physical frequency stopped (`STOPPED`);
2. `02440B88#00` -> controller shutdown settling complete (`OFF_IDLE`).

On the tested installation, `OFF_IDLE` can arrive roughly one minute after the engine reaches 0 Hz. A START sent during that interval was transmitted but ignored by Scheiber. Starting again after `OFF_IDLE` succeeded.

Bridge 5.4.2 does **not** queue an early START. Wait for `OFF_IDLE` before requesting a new start.

## Native Victron timed runs

Timed runs are manager-owned and were proven end-to-end:

```text
/ManualStart = 1
/ManualStartTimer > 0
/RunningByCondition = 'manual'
/RunningByConditionCode = 1
```

`/ManualStartTimer` counts down while `/Runtime` counts up. At expiry, Victron writes `/Start=0`; the bridge sends exactly one `02460B88#02`; Scheiber shutdown feedback updates `/StatusCode`.

Current gui-v2 may show the timed-run icon without exposing the older live +/- duration controls. That is a Victron UI behavior; the timer backend remains native and writable. No gui-v2 patch is included here.

### D-Bus CLI type warning

When manually writing `/ManualStartTimer`, use an integer variant. With Victron's `dbus` utility, `%12000` is an integer; plain `12000` may become a string. A string timer can crash `dbus-generator` when it performs integer arithmetic. Prefer the Victron UI.

## Generator-manager restart recovery

The bridge protects a running generator if `dbus-generator/startstop1` disappears and is recreated. Without this guard, a replacement manager initializes `/Start=0`, which can look like a real STOP.

The bridge:

- caches `/ManualStart`, `/ManualStartTimer`, running condition, and state;
- enters a 30 s recovery guard while the physical genset is STARTING/RUNNING;
- suppresses the replacement manager's initialization `/Start=0` from CAN;
- restores a numeric timed-run value and manual ownership where applicable;
- suppresses the duplicate synchronized `/Start=1` transmission.

Look for `MANAGER RECOVERY` in `bridge.log` when validating this path.

## AC source-state monitoring

Receive-only mappings:

| CAN ID | Meaning |
|---|---|
| `0x02400B90` | AC panel applied source |
| `0x02400B88` | House panel applied source |
| `0x02140898` | MasterVolt Inverter / AC ramp transition marker (0x02 OFF, 0x03 ON) |
| `0x02040B90` bytes 4-5 BE | AC panel voltage |
| `0x02040B88` bytes 4-5 BE | House panel voltage |

Source enum:

```text
01 = OFF
02 = SHORE
04 = GENERATOR
08 = INVERTER (Effective House source when Mastervolt is active)
```

Inverter & AC D-Bus paths on `com.victronenergy.genset.scheiber`:
- `/Scheiber/HousePanelAppliedSource` & `/Scheiber/HousePanelAppliedSourceText`
- `/Scheiber/AcPanelAppliedSource` & `/Scheiber/AcPanelAppliedSourceText`
- `/Scheiber/MastervoltInverterState` & `/Scheiber/MastervoltInverterStateText`
- `/Scheiber/HousePanelVoltage` & `/Scheiber/AcPanelVoltage`
- `/Scheiber/HousePanelFrequencyStatus` & `/Scheiber/AcPanelFrequencyStatus`

Node-RED flow `cerbo/node-red-ac-power-flow.json` provides real-time power routing matrix monitoring.

## Tank services

Confirmed frame `0x02040580` contains big-endian `uint16` percentages:

| Bytes | Tank | Vessel capacity |
|---|---|---:|
| 0-1 | Fresh water | 600 L |
| 2-3 | Diesel tank 1 | 500 L |
| 4-5 | Diesel tank 2 | 500 L |

Published services:

```text
com.victronenergy.tank.scheiber_fresh
com.victronenergy.tank.scheiber_diesel1
com.victronenergy.tank.scheiber_diesel2
```

### Tank units

The configuration remains in litres for human readability, but Victron D-Bus volume paths use cubic metres:

```text
/Level      percent
/Capacity   m3
/Remaining  m3
```

Therefore:

```text
600 L -> /Capacity 0.600
500 L -> /Capacity 0.500
```

For example, 74% of a 600 L fresh-water tank is:

```text
/Level      74.0
/Capacity   0.600
/Remaining  0.444
```

Verify all three after installation:

```bash
for s in \
  com.victronenergy.tank.scheiber_fresh \
  com.victronenergy.tank.scheiber_diesel1 \
  com.victronenergy.tank.scheiber_diesel2
do
    echo "===== $s ====="
    for p in Level Capacity Remaining FluidType CustomName; do
        printf '%-12s ' "$p:"
        dbus -y "$s" "/$p" GetValue
    done
done
```

The tank service text formatter converts m3 back to litres for human-readable display. Signal K receives the correct SI values directly from D-Bus.

## Battery services

### Six house batteries

```text
06020580 06060580 060A0580 060E0580 06120580 06160580
```

Per frame:

| Bytes | Decode | Confidence |
|---|---|---|
| 0-1 | LE16 x0.01 V | confirmed |
| 2-3 | `(LE16 - 0x4E00) * 0.1 A` | sign/offset strong; scale candidate |
| 4-5 | LE16 x1 % SoC | confirmed for this installation |

Physical house-battery 1-6 ordering remains to be validated.

### Engine batteries

```text
06140580 -> Engine Battery A
06180580 -> Engine Battery B
```

The current `0.00053 V/count` scale is experimental and produces plausible ~13.6 V values. Port/starboard identity and scale still need crank validation.

### Generator starter

`00501020` bytes 0-1 LE x0.1 V is published as generator starter voltage. Its current and AC-input fields remain diagnostic/candidate data.

## Rollback

The installer backs up the previous runtime script before replacement:

```text
/data/scheiber-gx/bridge.py.previous
```

Manual rollback:

```bash
svc -d /service/scheiber-gx
cp /data/scheiber-gx/bridge.py.previous /data/scheiber-gx/bridge.py
chmod 755 /data/scheiber-gx/bridge.py
python3 -m py_compile /data/scheiber-gx/bridge.py
svc -u /service/scheiber-gx
```

To disable the integration while retaining files:

```bash
./cerbo/uninstall.sh
```

## Diagnostic capture

For a labelled passive capture:

```bash
mkdir -p /data/scheiber-captures
OUT=/data/scheiber-captures/capture-$(date +%Y%m%d-%H%M%S).log
candump -L can2 > "$OUT"
```

Do not use broad CAN replay as a diagnostic technique on the live vessel bus.
