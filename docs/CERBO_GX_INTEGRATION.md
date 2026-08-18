# Victron Cerbo GX integration

This document describes the tested Scheiber CAN integration for a Victron Cerbo GX using a DSD TECH SH-C30A USB-CAN adapter (`gs_usb`). It is intentionally separate from the passive capture/analyzer workflow: the analysis tools remain read-only, while the optional Cerbo bridge can transmit the two generator commands that were live-validated on this installation.

## Status

Tested on:

- Victron Cerbo GX
- Venus OS v3.75 (`20260624163305 v3.75`)
- Linux `6.12.90-venus-2`, armv7l
- DSD TECH SH-C30A exposed as `can2` through `gs_usb`
- Scheiber CAN at 250 kbit/s with 29-bit extended identifiers
- bridge version **5.4.1**
- repository bridge SHA-256: `c4b6f4615b0a388e63c3aec315979154f9b7aed44a18d8e226b36877b8dd3ee3`
- field-tested v5.4.1 source SHA-256 before comment-only documentation reconciliation: `b7acb294467147a50166ac1468fe64de37c8a0facca920f3d0e8f2f89ee5a5c1`

The repository copy differs from the field-tested file only in comments/docstrings that were reconciled with later confirmed SoC/capacity/restart findings; executable Python statements are unchanged.

The bridge publishes a native connected-genset service:

```text
com.victronenergy.genset.scheiber
```

Victron `dbus-generator` then creates and owns the normal connected-genset manager, typically:

```text
com.victronenergy.generator.startstop1
```

The bridge also publishes three tank services and, when the GX system battery has been explicitly selected, six house-battery services plus two experimental engine-battery services.

## Safety boundary

The following generator commands were tested live on this installation:

```text
02460B88#01   START
02460B88#02   STOP
```

The bridge sends each requested command once and deliberately does **not** implement automatic CAN retries. Generator feedback is derived from independent Scheiber status/frequency frames and is published to Victron as `/StatusCode`.

The bridge does **not** transmit AC/House source-selector commands. In particular, it does not send `0x02420B90` or `0x02420B88`. Those selector request IDs are documented for analysis only.

Live validation on one vessel is not an OEM protocol guarantee. Preserve existing generator safety systems and use qualified marine-electrical practices.

## Wiring

Scheiber six-pin connector to SH-C30A:

| Scheiber pin | Function | SH-C30A |
|---:|---|---|
| 5 | CAN-H | CAN_H |
| 6 | CAN-L | CAN_L |
| 2 or installation-specific 3 | GND | GND |
| 1 | Recovery | leave open |
| 4 | +12 V | **never connect to SH-C30A** |

The SH-C30A is USB powered. On an existing correctly terminated Scheiber bus, leave the adapter's 120-ohm termination **OFF**. With vessel power off, approximately 60 ohms between CAN-H and CAN-L indicates the usual two 120-ohm end terminators.

## Venus OS prerequisites

No Debian/Ubuntu package installation is required. The tested Venus OS image already provided:

- `python3`
- `dbus`
- Victron `velib_python` / `vedbus.py`
- `ip`
- `candump` and `cansend`
- runit `svc`

The bridge searches common Victron `velib_python` locations at runtime.

Confirm the USB-CAN interface before installing:

```bash
lsusb
lsmod | grep -E 'gs_usb|can'
ip -details link show
```

The tested adapter enumerated as `can2`. If yours differs, install with `CAN_IF=canX` or edit the runit service environment.

## Required GX configuration before starting the bridge

### 1. Explicitly select the existing system battery

The bridge refuses to register its additional `com.victronenergy.battery.*` services while the GX battery selection is `default`. This prevents one of the Scheiber per-battery services from displacing the vessel's existing SmartShunt as the system battery.

Check the setting:

```bash
dbus -y com.victronenergy.settings \
  /Settings/SystemSetup/BatteryService GetValue
```

If it returns `default`, use the Venus OS UI to explicitly select the existing SmartShunt/system battery, then restart the bridge. Generator and tank integration do not depend on the extra battery services.

### 2. Configure AC input roles in Venus OS

For the tested installation:

```text
AC input 1 = Shore power
AC input 2 = Generator
```

The corresponding settings were:

```text
/Settings/SystemSetup/AcInput1 = 3
/Settings/SystemSetup/AcInput2 = 2
```

The bridge reads Scheiber source state for diagnostics but does not rewrite these Victron settings.

## Installation

### Recommended: install directly from GitHub

SSH to the Cerbo as root and run:

```bash
mkdir -p /data/scheiber-gx-installer
cd /data/scheiber-gx-installer

wget -O install.sh \
  https://raw.githubusercontent.com/danielkope/scheiber-can-analysis-nmea2000/main/cerbo/install.sh
chmod +x install.sh

CAN_IF=can2 CAN_BITRATE=250000 ./install.sh
```

The installer:

1. creates `/data/scheiber-gx`;
2. installs the pinned v5.4.1 `bridge.py` and verifies its SHA-256;
3. installs the runit `service/run` wrapper;
4. creates `/service/scheiber-gx -> /data/scheiber-gx/service`;
5. adds an idempotent service-link line to `/data/rc.local` so the link is recreated after reboot/update;
6. starts the service with `svc`.

### Install from a checked-out copy

If the repository has already been copied to the Cerbo:

```bash
cd /path/to/scheiber-can-analysis-nmea2000
CAN_IF=can2 CAN_BITRATE=250000 ./cerbo/install.sh
```

The installer uses the local `cerbo/bridge.py` and `cerbo/service/run` when present, so no network download is required.

## Files on the Cerbo

```text
/data/scheiber-gx/bridge.py
/data/scheiber-gx/service/run
/data/scheiber-gx/bridge.log
/data/scheiber-gx/status.json
/service/scheiber-gx -> /data/scheiber-gx/service
```

The persistent files live under `/data`. The `/service` symlink is recreated from `/data/rc.local`.

## First verification

### SocketCAN

```bash
ip -details -statistics link show can2
```

Expected essentials:

- bitrate `250000`
- interface `UP`
- no rapidly increasing RX/TX errors or bus-off events

Watch traffic without transmitting:

```bash
candump -L can2
```

### Bridge service

```bash
tail -n 100 /data/scheiber-gx/bridge.log
cat /data/scheiber-gx/status.json
```

Useful runit commands on the tested image:

```bash
svc -d /service/scheiber-gx   # stop
svc -u /service/scheiber-gx   # start
svc -t /service/scheiber-gx   # restart
```

`sv` was not installed on the tested Venus image; use `svc`.

### Connected genset D-Bus service

```bash
for p in ProductName Connected RemoteStartModeEnabled Start StatusCode; do
    printf '%-28s ' "$p:"
    dbus -y com.victronenergy.genset.scheiber /$p GetValue
done
```

Expected when healthy and stopped:

```text
ProductName:                 'Scheiber Generator'
Connected:                   1
RemoteStartModeEnabled:      1
Start:                       0
StatusCode:                  0
```

Then confirm Victron matched it with `startstop1`:

```bash
for p in Enabled GensetService GensetServiceType GensetInstance \
         State ManualStart ManualStartTimer RunningByCondition \
         RunningByConditionCode Runtime; do
    printf '%-28s ' "$p:"
    dbus -y com.victronenergy.generator.startstop1 /$p GetValue
done
```

`GensetService` should point at `com.victronenergy.genset.scheiber` and `Enabled` should be `1`.

## Generator-control architecture

The D-Bus ownership rule is important:

- `com.victronenergy.genset.scheiber /Start` is **Victron command state**.
- Scheiber CAN feedback never writes `/Start` locally.
- `... /StatusCode` is **physical generator feedback**.
- A physical/external Scheiber START is adopted into Victron by setting the manager's `/ManualStart=1`.
- When Victron subsequently writes `/Start=1`, the bridge suppresses the duplicate CAN START.
- A physical STOP clears `/ManualStart` only when manual ownership is active; automatic Victron conditions are not silently disabled.

This preserves native Victron generator start/stop conditions, timed runs, runtime accounting, and UI state.

### Victron status mapping

| Physical state | Victron `/StatusCode` |
|---|---:|
| OFF / idle / stopped | 0 |
| STARTING | 1 |
| RUNNING / RUNNING_SETTLED | 8 |
| STOPPING | 9 |
| actual error only | 10 |

## Confirmed generator CAN mapping

### Command frame: `0x02460B88`

| Payload | Meaning | Live transmit status |
|---|---|---|
| `01` | START | confirmed |
| `02` | STOP | confirmed |

For direct low-level diagnostics only:

```bash
cansend can2 02460B88#01   # START
cansend can2 02460B88#02   # STOP
```

Normal operation should use the Victron generator UI or D-Bus manager, not direct `cansend`.

### Lifecycle feedback: `0x02440B88`

| Payload | Bridge interpretation |
|---|---|
| `00` | `OFF_IDLE` |
| `01` | `RUNNING_SETTLED` |
| `02`, `03` | `STARTING` |
| `04`, `05` | `STOPPING` |
| `06`, `07` | observed abort/error candidates; unresolved |

### Generator frequency: `0x005A1020`

Bytes 0-1 are `uint16` little-endian x0.1 Hz.

Examples:

```text
F4 01 -> 500 -> 50.0 Hz
90 01 -> 400 -> 40.0 Hz
00 00 -> 0.0 Hz
```

Live testing showed this signal is generator-specific: with the generator off while shore power remained present, `0x005A1020` stayed at 0 Hz while the shared `0x02040898` AC telemetry still showed approximately 235 V / 50 Hz.

The bridge requires 47-53 Hz and a 3 s hold before declaring RUNNING. A 0 Hz generator-specific sample confirms physical STOPPED.

## Important post-stop behavior

Scheiber has two useful stopped milestones:

1. `005A1020 = 0.0 Hz` -> engine/frequency has stopped (`STOPPED`).
2. `02440B88#00` -> controller has finished its shutdown settling (`OFF_IDLE`).

On the tested installation, `#00` can arrive roughly one minute after the engine has already stopped. A START sent during that interval was transmitted correctly by the bridge but ignored by the Scheiber controller. Starting again after `OFF_IDLE` worked.

**Current v5.4.1 limitation:** the bridge does not queue an early Victron START until `OFF_IDLE`. After a stop, wait for `OFF_IDLE` before requesting another start. A future bridge version may add a one-shot queued-start behavior without changing Victron's timer semantics.

## Native timed runs

Victron timed runs work through `com.victronenergy.generator.startstop1`:

```text
/ManualStart = 1
/ManualStartTimer > 0
/RunningByCondition = 'manual'
/RunningByConditionCode = 1
```

`/ManualStartTimer` counts down while `/Runtime` counts up. When the timer reaches zero, Victron writes `/Start=0`; the bridge sends exactly one `02460B88#02`, and physical shutdown feedback updates `/StatusCode`.

Current gui-v2 versions may show the timer icon without exposing the old live `+/-` timer adjustment controls. That is a Victron UI behavior; the backend timer itself remains native and writable. No gui-v2 patch is included in this repository.

### D-Bus CLI type warning

If manually writing `/ManualStartTimer`, pass an integer variant. With Victron's `dbus` command, `%12000` is an integer; plain `12000` may be interpreted as a string. A string timer can crash `dbus-generator` when it attempts integer arithmetic.

Prefer the Victron UI. If CLI testing is necessary, verify the value immediately with `GetValue`.

## Generator-manager restart recovery

v5.4.1 contains a specific recovery guard for `dbus-generator` restarts. Without it, a newly recreated `startstop1` initializes its connected genset `/Start` to zero, which can look like a real STOP while the physical generator is already running.

The bridge now:

- caches manager `/ManualStart`, `/ManualStartTimer`, running condition, and state;
- enters a 30 s recovery guard if `startstop1` disappears while STARTING/RUNNING;
- suppresses the replacement manager's initialization `/Start=0` from CAN;
- restores manual ownership and a numeric timed-run value when applicable;
- suppresses the duplicate synchronized `/Start=1` CAN transmission.

Look for `MANAGER RECOVERY` messages in `bridge.log` when validating this path.

## AC source-state monitoring

These IDs are receive-only in the bridge:

| CAN ID | Meaning |
|---|---|
| `0x02400B90` | AC panel applied source |
| `0x02400B88` | House panel applied source |
| `0x02040B90` bytes 4-5 BE | AC panel voltage |
| `0x02040B88` bytes 4-5 BE | House panel voltage |

Source enum:

```text
01 = OFF
02 = SHORE
04 = GENERATOR
```

The corresponding request IDs `0x02420B90` and `0x02420B88` are **not transmitted** by this bridge.

There is currently no synthetic `com.victronenergy.acsystem.scheiber` service. On systems without VE.Bus/acsystem, SystemCalc may therefore place the connected genset in a generic/positional AC-input slot and the UI can show a misleading Grid label. This is a topology/UI issue, not a generator-control failure.

## Tank services

Confirmed frame `0x02040580` contains big-endian `uint16` percentage values:

| Bytes | Tank | Capacity configured in bridge |
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

Tank telemetry is sample-and-hold rather than being invalidated merely because a frame is sparse.

## Battery services

### Six house batteries

| CAN ID | Voltage | Current | SoC |
|---|---|---|---|
| `0x06020580` | bytes 0-1 LE x0.01 V | bytes 2-3 LE, `(raw-0x4E00)*0.1 A` candidate scale | bytes 4-5 LE, SoC % confirmed for this installation |
| `0x06060580` | same | same | same |
| `0x060A0580` | same | same | same |
| `0x060E0580` | same | same | same |
| `0x06120580` | same | same | same |
| `0x06160580` | same | same | same |

The physical battery 1-6 ordering is not yet proven. Voltage is confirmed. Current sign/offset is strong; the x0.1 A scale remains a working candidate. The third word is treated as SoC, not temperature, based on installation validation.

### Engine batteries

```text
0x06140580 -> Engine Battery A (experimental)
0x06180580 -> Engine Battery B (experimental)
```

The current bridge uses an experimental voltage scale of `0.00053 V/count`, producing plausible ~13.6 V values in the observed data. Physical port/starboard identity and scale still need one-engine-at-a-time crank validation.

### Generator starter battery

`0x00501020` bytes 0-1 are decoded little-endian x0.1 V and published as `/StarterVoltage`. The same frame also carries candidate charger current and AC-input voltage diagnostics.

## Startup resynchronization

When the bridge starts while the generator is already running, it tries to recover physical state rather than assuming OFF. Generator-specific `0x005A1020` nominal frequency and lifecycle feedback are the strongest evidence.

v5.4.1 also uses two consecutive high-AC samples from `0x00501020` as a fast startup-resync hint. That field belongs to the `0x1020` charger family and should not be treated as the sole long-term proof of generator state; the later generator-specific frequency/status frames remain authoritative.

## Debugging

### Service not running

```bash
ls -l /service/scheiber-gx
ps | grep '[b]ridge.py'
tail -n 120 /data/scheiber-gx/bridge.log
svc -t /service/scheiber-gx
```

### `can2` missing

```bash
lsusb
lsmod | grep -E 'gs_usb|can'
modprobe can
modprobe can_raw
modprobe gs_usb
ip -details link show
```

If the adapter enumerated under another name, reinstall with the correct `CAN_IF` or adjust the runit wrapper.

### Bus errors / no traffic

```bash
ip -details -statistics link show can2
candump -L can2
```

Check:

- 250 kbit/s
- H/L polarity
- common ground
- termination
- adapter programming switch in normal mode
- vessel Scheiber network awake

Disconnect the adapter if error counters rise rapidly or the interface repeatedly goes bus-off.

### Generator appears but cannot be controlled

```bash
dbus -y com.victronenergy.genset.scheiber /Connected GetValue
dbus -y com.victronenergy.genset.scheiber /RemoteStartModeEnabled GetValue
dbus -y com.victronenergy.genset.scheiber /Start GetValue
dbus -y com.victronenergy.generator.startstop1 /Enabled GetValue
dbus -y com.victronenergy.generator.startstop1 /GensetService GetValue
```

Also inspect the bridge log for `Victron requested START/STOP` and the corresponding single `TX 02460B88#01/#02` line.

### Generator stopped but immediate restart does nothing

Look for:

```text
ACTUAL GENERATOR STATE: ... -> STOPPED
```

followed later by:

```text
RX generator state 02440B88#00
... -> OFF_IDLE
```

Wait for `OFF_IDLE` before restarting on v5.4.1.

### Battery services do not appear

Check:

```bash
dbus -y com.victronenergy.settings \
  /Settings/SystemSetup/BatteryService GetValue
```

If it is `default`, explicitly select the existing SmartShunt/system battery and restart the bridge. The log intentionally explains this safety refusal.

### Manager disappeared/restarted

The bridge should log `MANAGER RECOVERY armed`, rematch `startstop1`, restore manual/timed ownership if needed, and then log `MANAGER RECOVERY complete`. It should **not** send a synthetic STOP just because the replacement manager initialized `/Start=0`.

## Status snapshot

The bridge writes `/data/scheiber-gx/status.json` every few seconds. It includes:

- physical generator state and reason;
- latest frequency/starter/AC diagnostics;
- panel applied-source values;
- manager cache and recovery state;
- battery samples;
- tank samples.

This is the quickest single file to attach when reporting a bridge issue.

## Uninstall / rollback

Disable the service while leaving persistent files for recovery:

```bash
/data/scheiber-gx-installer/uninstall.sh
```

or from a repository checkout:

```bash
./cerbo/uninstall.sh
```

The installer keeps the prior bridge at `/data/scheiber-gx/bridge.py.previous` when updating an existing installation. A manual rollback is:

```bash
svc -d /service/scheiber-gx
cp /data/scheiber-gx/bridge.py.previous /data/scheiber-gx/bridge.py
svc -u /service/scheiber-gx
```

## Known follow-up work

Not implemented in v5.4.1:

- queue a Victron START requested during post-stop settling until `02440B88#00` / `OFF_IDLE`;
- publish a synthetic two-input `com.victronenergy.acsystem.scheiber` service for Shore/Generator topology;
- AC/House source-selector control;
- HVAC/air-conditioning CAN decoding;
- final physical port/starboard engine-battery identity and calibrated scale;
- gui-v2 timer-control restoration.

The first two items should be implemented independently: generator control is already functional without AC-source control, and the AC-system model must not expose writable source-control paths unless they are intentionally supported.
