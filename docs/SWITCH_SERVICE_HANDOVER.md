# Scheiber native GX switch service — implementation and field handover

## 1. Purpose and status

This document hands over the first active implementation of the Scheiber
Multibloc V8 sailing-panel controls as a native Victron Venus OS switch device.
It is built on the decoded evidence in PR #7, especially
`docs/control-panel-v8/panel_mapping.json`, the labelled captures and the
`scheiber_v8_panel.py` reference decoder.

The implementation is ready for controlled vessel testing. It has been
regression-tested off-vessel, but the following still require live validation:

1. the six CAN RTR state requests on this exact installation;
2. externally injected `0x04001808` press/release events;
3. physical-panel/GX state convergence after a remote command;
4. bilge running feedback during an AUTO-triggered cycle.

The first active control must be a non-critical lighting circuit. Do not begin
with a bilge pump.

## 2. Files and process separation

```text
cerbo/bridge.py                     existing field-tested generator/telemetry process
cerbo/scheiber_switch_protocol.py   pure CAN mapping, state model and command planner
cerbo/switch_service.py             D-Bus + SocketCAN runtime
cerbo/service/run                   existing runit entrypoint
cerbo/service-switch/run            new switch-service runit entrypoint
cerbo/install.sh                    installs and starts both services
cerbo/uninstall.sh                  disables both services
```

The switch runtime is intentionally separate from `bridge.py`:

```text
Scheiber CAN (can2)
       │
       ├── scheiber-gx
       │     └── genset / tanks / batteries
       │
       └── scheiber-switch
             └── com.victronenergy.switch.scheiber
```

Linux raw CAN sockets independently receive the same frames, so no internal
message broker is required. The existing `scheiber-gx` runit service owns CAN
interface configuration; `scheiber-switch` waits until that interface is UP at
the persisted bitrate.

## 3. Logical GX controls

| GX channel | UI | Scheiber output(s) | Key(s) | Actual-running signal |
|---|---|---:|---|---|
| Electronics | Toggle | 1 | `0x02` | — |
| Deck Floodlight | Toggle | 2 | `0x05` | — |
| Navigation Lights | Toggle | 3 | `0x03` | — |
| Anchor Light | OFF/AUTO/ON | 4 | `0x06` | — |
| Steaming Light | Toggle | 5 | `0x04` | — |
| Port Bilge Pump | OFF/AUTO/ON | 6 AUTO + 7 MANUAL | `0x08`, `0x0C` | `0x02141808` bit 1 |
| Starboard Bilge Pump | OFF/AUTO/ON | 8 AUTO + 9 MANUAL | `0x09`, `0x0D` | `0x02141808` bit 2 |
| Fresh Water Pump | OFF/AUTO/ON | 10 enable | `0x0A` | `0x02141808` bit 0 |
| Fridge Unit | Toggle | 11 | `0x0B` | — |
| General Lighting | Toggle | 12 | `0x07` | — |

The native D-Bus service is:

```text
com.victronenergy.switch.scheiber
```

Switch paths use:

```text
/SwitchableOutput/<channel>/State
/SwitchableOutput/<channel>/Auto             # three-state channels
/SwitchableOutput/<channel>/Status
/SwitchableOutput/<channel>/Settings/...
/SwitchableOutput/<channel>/Scheiber/...
```

Running indicators are also published as discrete inputs:

```text
/GenericInput/fresh_water_pump_running
/GenericInput/bilge_port_running
/GenericInput/bilge_starboard_running
```

## 4. State is authoritative; commands are requests

The physical panel key frame is:

```text
CAN ID  0x04001808
press   00 00 00 01 (key | 0x80)
release 00 00 00 01 key
```

A press/release pair does not encode ON or OFF. It asks the distributed
Scheiber system to process that key. Therefore the service never sends a blind
key press.

At service start:

```text
all outputs = UNKNOWN
```

The six paired output-state frames are:

```text
0x02161808 outputs 1–2
0x02181808 outputs 3–4
0x021A1808 outputs 5–6
0x021C1808 outputs 7–8
0x021E1808 outputs 9–10
0x02201808 outputs 11–12
```

Slot 1 uses byte 2 bit 0; slot 2 uses byte 6 bit 0. The runtime listens
passively and also sends candidate RTR requests with DLC 8. Until the relevant
state has been learned, a D-Bus write is rejected.

A normal binary command transaction is:

```text
D-Bus desired state
       │
       ├── actual UNKNOWN → reject
       ├── actual already desired → no CAN transmission
       └── actual differs
                │
                ├── press key
                ├── ~150 ms
                ├── release key
                └── wait for matching output-state frame
                         ├── match → complete
                         └── no match in 4 s → OutputFault
```

There are no automatic key retries. A repeated key on a toggle circuit could
reverse the intended state, so a timeout becomes an explicit fault requiring
new operator action.

## 5. Bilge state model

Each bilge has separate Scheiber AUTO and MANUAL output bits. The three stable
states observed are:

```text
OFF     AUTO=0  MANUAL=0
AUTO    AUTO=1  MANUAL=0
MANUAL  AUTO=1  MANUAL=1
```

`AUTO=0, MANUAL=1` is unobserved and is treated as invalid. The planner uses
explicit transition paths that never create it:

| From | To | Key sequence |
|---|---|---|
| OFF | AUTO | AUTO |
| OFF | MANUAL | AUTO, then MANUAL |
| AUTO | OFF | AUTO |
| AUTO | MANUAL | MANUAL |
| MANUAL | AUTO | MANUAL |
| MANUAL | OFF | MANUAL, then AUTO |

Every step waits for CAN confirmation before the next key is pressed.

Native GX presentation uses the three-state control:

```text
GX OFF  → Scheiber OFF
GX AUTO → Scheiber AUTO
GX ON   → Scheiber MANUAL / forced pumping
```

Actual pump activity is separate. In AUTO, the mode should remain AUTO while
the running bit changes OFF → ON → OFF as the float/logic cycles the motor.
The bits have been observed during MANUAL tests; the AUTO-cycle interpretation
is highly likely but remains a specific field-validation item.

## 6. Freshwater pump model

Output 10 means the freshwater pressure system is enabled. It does not mean the
motor is currently turning.

```text
output 10              enable/disable state
0x02141808 bit 0       actual motor/demand activity
```

The three-state GX control uses `Auto` as automation ownership:

```text
OFF   system disabled
AUTO  Node-RED owns the enabled state
ON    system manually enabled
```

The switch runtime only persists the Auto preference. It does not implement
leak, tank-level or unattended-vessel policies; those belong in Node-RED.

Anchor Light uses the same ownership model: Auto is persisted, while Node-RED
will later write the physical `State` according to sunset/sunrise rules.

## 7. Connection loss and restart behavior

The panel emits an ALIVE frame approximately once per second. Any recognized
panel frame marks the service connected. If no recognized activity is seen for
five seconds:

- `/Connected` becomes 0;
- any pending command fails;
- every physical state and running signal becomes UNKNOWN;
- switch status becomes disabled;
- no command is accepted until state is learned again.

The service stores only automation ownership for Anchor Light and Fresh Water
Pump. It deliberately does not persist physical output state.

Diagnostics:

```text
/data/scheiber-gx/switch.log
/data/scheiber-gx/switch-status.json
/data/scheiber-gx/switch-settings.json
```

## 8. Installation and receive-only option

From a checked-out branch on the Cerbo:

```bash
CAN_IF=can2 CAN_BITRATE=250000 \
SWITCH_TX_ENABLED=1 SWITCH_RTR_ENABLED=1 \
./cerbo/install.sh
```

For a receive-only first UI inspection:

```bash
CAN_IF=can2 CAN_BITRATE=250000 \
SWITCH_TX_ENABLED=0 SWITCH_RTR_ENABLED=1 \
./cerbo/install.sh
```

`SWITCH_TX_ENABLED=1` is the requested first active build. The runtime still
rejects writes while disconnected or unsynchronized.

Verify:

```bash
sv status /service/scheiber-gx /service/scheiber-switch

dbus -y com.victronenergy.switch.scheiber /Connected GetValue
dbus -y com.victronenergy.switch.scheiber \
  /Scheiber/SynchronizedOutputCount GetValue
dbus -y com.victronenergy.switch.scheiber \
  /Scheiber/SynchronizedOutputs GetValue
```

Expected fully synchronized output count:

```text
12
```

## 9. Controlled field-test sequence

### Stage A — passive/UI validation

1. Install with TX disabled if a visual-only check is preferred.
2. Confirm the native Switch pane shows ten controls in Systems, Lighting,
   Navigation and Pumps groups.
3. Operate each ordinary physical panel key and confirm GX follows it.
4. Confirm bilge physical states resolve to OFF, AUTO or ON/MANUAL correctly.
5. Open a tap and confirm Fresh Water Pump Running changes independently of the
   pump enable control.

### Stage B — RTR validation

1. Start `candump -L can2` before restarting `scheiber-switch`.
2. Confirm the six RTR requests are transmitted.
3. Confirm each request receives its expected data frame.
4. Save a new immutable capture and annotate exact restart time.
5. If no replies are seen, disable RTR and rely on passive frames until the
   request mechanism is understood. Do not initialize states to OFF.

### Stage C — first active command: Deck Floodlight

1. Enable TX and restart the switch service.
2. Confirm output count is 12 and no command is pending.
3. Command Deck Floodlight ON in GX.
4. Confirm exactly one press and one release for key `0x05`.
5. Confirm output 2 becomes ON in `0x02161808`.
6. Confirm the physical panel indicator and GX agree.
7. Command OFF and repeat.
8. Press the physical key and confirm GX follows without transmitting a second
   key event.

Abort on any duplicate key event, timeout, incorrect output, panel disagreement
or unexpected interlock.

### Stage D — other non-critical circuits

Repeat the same process for General Lighting, Anchor Light, Navigation Lights,
Electronics, Fridge and Steaming Light. When testing Steaming Light, explicitly
confirm that Scheiber still turns Navigation Lights on and that the GX
navigation control updates from feedback.

### Stage E — pump controls

1. Validate Fresh Water OFF/ON without an open tap.
2. Open a tap and validate the running indicator.
3. Validate bilge OFF ↔ AUTO on one side at a time.
4. Validate AUTO ↔ MANUAL only with the pump discharge path clear.
5. Trigger a controlled float-switch AUTO cycle and capture the running bit.
6. Do not enable unattended automation until that AUTO-cycle evidence exists.

## 10. Node-RED follow-on plan

Node-RED must write D-Bus, not CAN. The switch service remains the only CAN
command owner.

### Anchor light

Recommended policy:

```text
Mode OFF     automation does nothing; light forced off
Mode AUTO    sunset → ON; sunrise + 1 hour → OFF
Mode ON      manual forced on
```

Store an absolute shutdown deadline rather than an in-memory delay so a Cerbo
restart does not reset an eight-hour maximum runtime.

### Freshwater pump

Possible AUTO rules:

- disable below a configured fresh-water tank threshold;
- disable when the vessel is unattended;
- warn and optionally disable after abnormal continuous runtime;
- alarm when disabled but running feedback remains active.

### Bilge alarms

Do not automatically stop a long-running bilge pump. Long runtime is evidence
of possible water ingress and should escalate alarms while pumping continues.

Suggested starting policy:

```text
running 0 → 1            immediate informational/warning event
running > 2 minutes      warning
running > 5 minutes      critical alarm
several cycles/hour      repeated-ingress warning
mode OFF + running       immediate anomaly alarm
MANUAL + no running      command/pump fault after a short confirmation delay
running 1 → 0            close event and record duration
```

Thresholds must be tuned from real vessel behavior.

## 11. Rollback

Disable both services without deleting data:

```bash
./cerbo/uninstall.sh
```

Disable only the new switch service:

```bash
svc -d /service/scheiber-switch
rm -f /service/scheiber-switch
```

The existing generator/telemetry service can remain running independently.
Installed files and `.previous` backups remain under `/data/scheiber-gx`.

## 12. Non-negotiable rules for future work

- Never assume OFF at startup.
- Never establish a baseline by turning every circuit off.
- Never flatten a bilge into a single boolean.
- Never infer running from mode/enable when `0x02141808` is available.
- Never send a second toggle automatically after an unconfirmed command.
- Never use direct output forcing without a separate evidence and safety review.
- Preserve Scheiber interlocks and treat CAN state frames as authoritative.
- Keep active-test captures immutable and document exact operator actions.
