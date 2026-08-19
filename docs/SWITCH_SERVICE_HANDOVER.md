# Scheiber native GX switch service — implementation and field handover

## 1. Purpose and current status

This document hands over the active Scheiber Multibloc V8 sailing-panel
integration as a native Victron Venus OS switch device. It is based on the
labelled CAN evidence and mappings in `docs/control-panel-v8/`.

The following has now been validated on the vessel:

- the service installs and starts on a Cerbo GX;
- all ten native switch controls render in the GX Switch pane;
- physical panel changes propagate to GX;
- active GX writes emit the expected momentary Scheiber key events;
- feedback-gated state convergence works for the tested circuits;
- reboot testing exposed unstable Linux `canN` enumeration for the USB adapter.

The remaining pump-specific validation item is a controlled bilge AUTO-triggered cycle to
confirm that the known bilge-running input bits behave in AUTO exactly as they
do during the already observed MANUAL tests.

## 2. Runtime architecture

```text
Scheiber CAN network
       │
       ├── gs_usb / candleLight adapter
       │       └── Linux name varies by boot: can0, can1, can2, ...
       │
       ├── scheiber-gx
       │       ├── resolves physical USB-CAN identity
       │       ├── configures bitrate and restart-ms
       │       ├── publishes /run/scheiber-can-if
       │       └── genset / tanks / batteries
       │
       └── scheiber-switch
               ├── waits for /run/scheiber-can-if
               └── com.victronenergy.switch.scheiber
```

Files:

```text
cerbo/bridge.py                     existing field-tested generator/telemetry process
cerbo/resolve_can_interface.py      stable USB identity -> current canN resolver
cerbo/scheiber_switch_protocol.py   pure CAN mapping, state model and command planner
cerbo/switch_service.py             D-Bus + SocketCAN switch runtime
cerbo/service/run                   main runit entrypoint and CAN owner
cerbo/service-switch/run            switch runit entrypoint
cerbo/install.sh                    transactional installer/updater
cerbo/uninstall.sh                  disables both services
```

The two Python services use independent raw CAN sockets and receive the same
frames. The main service is deliberately the single owner of physical interface
discovery and link configuration.

## 3. Stable CAN adapter identity

### 3.1 Field observation

After a Cerbo reboot, the USB adapter previously known as `can2` appeared as
`can0`. The same boot showed:

```text
can0  driver=gs_usb
can1  driver=sun4i_can
```

The external adapter exposes a stable USB identity:

```text
ID_VENDOR_ID=1d50
ID_MODEL_ID=606f
ID_SERIAL_SHORT=0025003C5457530220383638
ID_USB_DRIVER=gs_usb
```

The physical USB device path observed at that time was:

```text
/sys/devices/platform/soc/1c14400.usb/usb3/3-1/3-1:1.0
```

The USB port path is useful diagnostic information, but the serial number is the
preferred identity because port placement may change.

### 3.2 Resolution policy

`CAN_IF=auto` is the preferred configuration. At each main-service start,
`resolve_can_interface.py`:

1. enumerates CAN-like interfaces from `/sys/class/net`;
2. keeps only `gs_usb` interfaces for automatic discovery;
3. applies the exact configured USB serial when present;
4. optionally verifies USB vendor and product IDs;
5. accepts exactly one match;
6. fails closed if zero or multiple devices match.

It never chooses the first `canN` entry.

Explicit `CAN_IF=can0` remains supported for diagnostics or unusual hardware,
but it is not stable across boot ordering.

After successful resolution and link setup, `scheiber-gx` atomically writes the
current interface name to:

```text
/run/scheiber-can-if
```

`scheiber-switch` waits for that file and verifies that the published interface
is UP at the configured bitrate. It does not run a second, independent device
selection algorithm.

### 3.3 Persisted configuration

```text
/data/scheiber-gx/CAN_INTERFACE        auto or explicit interface selector
/data/scheiber-gx/CAN_BITRATE          normally 250000
/data/scheiber-gx/CAN_USB_SERIAL       stable adapter serial
/data/scheiber-gx/CAN_USB_VENDOR_ID    optional VID
/data/scheiber-gx/CAN_USB_PRODUCT_ID   optional PID
```

The runtime file under `/run` is intentionally not persistent; `/run` is reset
at boot and therefore cannot retain a stale `canN` assignment.

## 4. Logical GX controls

| GX channel | UI | Scheiber output(s) | Key(s) | Actual-running signal |
|---|---|---:|---|---|
| Electronics | Toggle | 1 | `0x02` | — |
| Deck Floodlight | Toggle | 2 | `0x05` | — |
| Navigation Lights | Toggle | 3 | `0x03` | — |
| Anchor Light | OFF/AUTO/ON | 4 | `0x06` | — |
| Steaming Light | Toggle | 5 | `0x04` | — |
| Port Bilge Pump | OFF/AUTO/ON | 6 AUTO + 7 MANUAL | `0x08`, `0x0C` | `0x02141808` bit 1 |
| Starboard Bilge Pump | OFF/AUTO/ON | 8 AUTO + 9 MANUAL | `0x09`, `0x0D` | `0x02141808` bit 2 |
| Fresh Water Pump | OFF/ON | 10 enable | `0x0A` | `0x02141808` bit 0 |
| Fridge Unit | Toggle | 11 | `0x0B` | — |
| General Lighting | Toggle | 12 | `0x07` | — |

The native D-Bus service is:

```text
com.victronenergy.switch.scheiber
```

Switch paths:

```text
/SwitchableOutput/<channel>/State
/SwitchableOutput/<channel>/Auto             # Anchor and bilges
/SwitchableOutput/<channel>/Status
/SwitchableOutput/<channel>/Settings/...
/SwitchableOutput/<channel>/Scheiber/...
```

Read-only activity inputs:

```text
/GenericInput/fresh_water_pump_running
/GenericInput/bilge_port_running
/GenericInput/bilge_starboard_running
```

## 5. State is authoritative; commands are requests

The physical panel key frame is:

```text
CAN ID  0x04001808
press   00 00 00 01 (key | 0x80)
release 00 00 00 01 key
```

A press/release pair is a momentary key event, not an explicit ON or OFF
command. Therefore every physical output begins `UNKNOWN` at process start.

The six paired state frames are:

```text
0x02161808 outputs 1–2
0x02181808 outputs 3–4
0x021A1808 outputs 5–6
0x021C1808 outputs 7–8
0x021E1808 outputs 9–10
0x02201808 outputs 11–12
```

Slot 1 uses byte 2 bit 0 and slot 2 uses byte 6 bit 0. A command is rejected
until its relevant physical state has synchronized.

Normal transaction:

```text
D-Bus desired state
       │
       ├── actual UNKNOWN          → reject
       ├── actual already desired  → no CAN transmission
       └── actual differs
                │
                ├── one key press
                ├── approximately 150 ms
                ├── one key release
                └── wait for matching state frame
                         ├── match     → complete
                         └── 4 s       → OutputFault
```

There are no automatic key retries. Repeating an unconfirmed toggle could
reverse the intended state.

Direct `CMD_S_TOR` output forcing is not used. This preserves distributed
Scheiber logic, including the observed Steaming Light -> Navigation Lights
interlock.

## 6. Bilge mode and activity semantics

Each bilge has separate Scheiber AUTO and MANUAL state bits:

```text
OFF     AUTO=0  MANUAL=0
AUTO    AUTO=1  MANUAL=0
MANUAL  AUTO=1  MANUAL=1
```

`AUTO=0, MANUAL=1` is unobserved and treated as invalid. Safe transitions are:

| From | To | Key sequence |
|---|---|---|
| OFF | AUTO | AUTO |
| OFF | MANUAL | AUTO, then MANUAL |
| AUTO | OFF | AUTO |
| AUTO | MANUAL | MANUAL |
| MANUAL | AUTO | MANUAL |
| MANUAL | OFF | MANUAL, then AUTO |

Each step waits for CAN confirmation before the next key event.

The GX three-state row has two simultaneous jobs:

- **Auto** represents the selected Scheiber AUTO mode.
- **On** represents manual force and also mirrors actual motor activity.

Expected visual states:

```text
OFF + not running       Off
AUTO + not running      Auto
AUTO + running          Auto + On
MANUAL                  On
```

MANUAL keeps On selected because it commands continuous pumping. During AUTO,
On follows the physical running bit. This mirrors the physical switchboard,
where the ON LED illuminates while the pump is actually pumping.

An unexpected `mode=OFF` plus `running=1` is deliberately visible and should be
raised as an anomaly alarm.

## 7. Fresh-water pressure pump semantics

Output 10 means the pressure system is enabled. It does not mean the motor
is currently turning:

```text
output 10              pressure system enabled/disabled
0x02141808 bit 0       motor currently ACTIVE due to demand
```

The GX control is therefore simply:

```text
OFF   pressure system disabled
ON    pressure system enabled; pressure switch controls motor demand
```

A separate activity card shows:

```text
Motor: Standby
Motor: ACTIVE
```

There is no user-facing Auto mode for this circuit. Automation can still write
the normal ON/OFF D-Bus state later, but the pressure switch remains the
low-level automatic motor controller.

Only Anchor Light persists an automation-ownership preference for future
sunrise/sunset Node-RED logic. Physical output state is never persisted.

## 8. Connection loss and restart behavior

The panel emits an ALIVE frame approximately once per second. If no recognized
panel activity is seen for five seconds:

- `/Connected` becomes 0;
- any pending command fails;
- physical output and running state return to UNKNOWN;
- controls become disabled;
- writes remain blocked until synchronization returns.

On reboot:

1. the main runit service loads `gs_usb`;
2. resolves the configured USB identity to the current `canN`;
3. configures 250 kbit/s with `restart-ms 100`;
4. brings the interface UP;
5. writes `/run/scheiber-can-if`;
6. starts the generator/telemetry bridge;
7. the switch service consumes the same runtime interface name.

Diagnostics:

```text
/data/scheiber-gx/bridge.log
/data/scheiber-gx/switch.log
/data/scheiber-gx/switch-status.json
/data/scheiber-gx/switch-settings.json
/run/scheiber-can-if
```

## 9. Installation/update

For a pinned branch or commit:

```sh
mkdir -p /data/scheiber-gx-installer
cd /data/scheiber-gx-installer

REF="<commit-sha>"
RAW_BASE="https://raw.githubusercontent.com/danielkope/scheiber-can-analysis-nmea2000/${REF}/cerbo"

curl -fL "${RAW_BASE}/install.sh" -o install.sh
chmod 755 install.sh

CAN_IF=auto \
CAN_USB_SERIAL=0025003C5457530220383638 \
CAN_USB_VENDOR_ID=1d50 \
CAN_USB_PRODUCT_ID=606f \
CAN_BITRATE=250000 \
SWITCH_TX_ENABLED=1 \
SWITCH_RTR_ENABLED=1 \
RAW_BASE="${RAW_BASE}" \
./install.sh
```

The installer can auto-enrol the serial if exactly one `gs_usb` interface exists
and no serial is supplied. Explicit pinning is preferred for long-term clarity.

Verify:

```sh
cat /run/scheiber-can-if
ip -details -statistics link show "$(cat /run/scheiber-can-if)"
sv status /service/scheiber-gx /service/scheiber-switch

dbus -y com.victronenergy.switch.scheiber /Connected GetValue
dbus -y com.victronenergy.switch.scheiber \
  /Scheiber/SynchronizedOutputCount GetValue
```

Expected synchronized output count:

```text
12
```

## 10. Remaining controlled field validation

### Bilge AUTO activity

For one side at a time:

1. place the bilge in AUTO;
2. confirm Auto is selected and On is not selected while idle;
3. safely trigger the float/automatic demand;
4. capture `0x02141808`;
5. confirm the relevant running bit becomes 1;
6. confirm GX displays **Auto + On**;
7. let the pump stop;
8. confirm the bit returns to 0 and GX returns to Auto only;
9. save the annotated capture as immutable evidence.

Do not enable unattended bilge alarm automation until this test is recorded.

## 11. Node-RED follow-on

Node-RED must write D-Bus, not CAN. The switch service remains the only CAN
command owner.

### Anchor light

```text
Mode OFF     light forced off; scheduling inactive
Mode AUTO    sunset -> ON; sunrise + 1 hour -> OFF
Mode ON      manual forced on
```

Use persisted absolute deadlines rather than memory-only delay nodes so Cerbo
restarts do not reset maximum runtimes.

### Fresh-water pump

Potential rules:

- disable below a configured tank threshold;
- disable when the vessel is unattended;
- warn and optionally disable after abnormal continuous activity;
- alarm when disabled but running feedback remains active.

### Bilge alarms

Do not automatically stop a long-running bilge. Long runtime can indicate water
ingress and should escalate alarms while pumping continues.

Suggested starting policy:

```text
running 0 -> 1            immediate event
running > 2 minutes       warning
running > 5 minutes       critical alarm
several cycles/hour       repeated-ingress warning
mode OFF + running        immediate anomaly alarm
MANUAL + no running       command/pump fault after confirmation delay
running 1 -> 0            close event and record duration
```

Thresholds must be tuned from actual vessel behaviour.

## 12. Rollback

Disable both services without deleting persistent data:

```sh
/data/scheiber-gx-installer/uninstall.sh
```

Disable only the switch service:

```sh
svc -d /service/scheiber-switch
rm -f /service/scheiber-switch
```

The generator/telemetry service can remain running independently.

## 13. Non-negotiable rules

- Never assume OFF at startup.
- Never establish a baseline by turning every circuit off.
- Never flatten a bilge into a single boolean.
- Never infer motor activity from mode when `0x02141808` is available.
- Never automatically repeat an unconfirmed toggle command.
- Never choose the first `canN` when USB identity is ambiguous.
- Never use direct output forcing without separate evidence and safety review.
- Preserve Scheiber interlocks and treat CAN state frames as authoritative.
- Keep active-test captures immutable and document exact operator actions.
