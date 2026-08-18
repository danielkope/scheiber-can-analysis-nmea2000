# Cerbo native switch integration — implementation and handover plan

Status: **first implementation for review/field validation**  
Scope base: control-panel reverse engineering from PR #7, commit `8da4e30da12e95559cfb3562a7775800f70a6616`.

## Goal

Publish the Scheiber Multibloc V8 switchboard as a native Venus OS `com.victronenergy.switch.scheiber` service so the standard GX Switch pane presents the vessel controls cleanly, while preserving Scheiber's own distributed logic/interlocks.

This integration deliberately uses **panel-style momentary key events** and actual state feedback. It does not use the source-derived direct output forcing command.

## Architecture

```text
Venus GX Switch UI / Node-RED
            |
            | D-Bus
            v
com.victronenergy.switch.scheiber
            |
            | desired-state controller
            v
   Scheiber panel key event 0x04001808
            |
            v
      Multibloc V8 logic
            |
            | 02xx1808 state + 02141808 running feedback
            v
      authoritative GX status
```

The switch bridge is a **separate runit process** from the existing field-tested generator/tank/battery bridge. Both processes can bind independent raw SocketCAN sockets to the same `can2` interface.

## Ten logical GX controls

| GX control | Native type | Scheiber state | Actual running/status |
|---|---:|---|---|
| Electronics | Toggle (1) | output 1 | output 1 |
| Deck Floodlight | Toggle (1) | output 2 | output 2 |
| Navigation Lights | Toggle (1) | output 3 | output 3 |
| Anchor Light | Three-state (9) | output 4 | output 4 |
| Steaming Light | Toggle (1) | output 5 | output 5 |
| Port Bilge Pump | Three-state (9) | outputs 6+7 | `0x02141808` bit 1 |
| Starboard Bilge Pump | Three-state (9) | outputs 8+9 | `0x02141808` bit 2 |
| Fresh Water Pump | Three-state (9) | output 10 enable | `0x02141808` bit 0 |
| Fridge Unit | Toggle (1) | output 11 | output 11 |
| General Lighting | Toggle (1) | output 12 | output 12 |

### Why bilges use native type 9, not Victron BilgePump type 10

Victron's BilgePump type 10 exposes AUTO/forced-ON plus running status, but Scheiber has a real **OFF / AUTO / MANUAL** mode. Type 9 exposes `/State` plus `/Auto` and can represent all three modes without discarding OFF.

Bilge native representation:

```text
GX OFF:     State=0 Auto=0 -> Scheiber AUTO=0 MANUAL=0
GX AUTO:    State=0 Auto=1 -> Scheiber AUTO=1 MANUAL=0
GX ON:      State=1 Auto=0 -> Scheiber AUTO=1 MANUAL=1 (MANUAL/forced)
```

The actual pump motor activity is independent and comes from `0x02141808`.

## Running-feedback confidence

`0x02141808` is modeled as actual motor-running feedback:

- bit 0: fresh-water pump running
- bit 1: port bilge running
- bit 2: starboard bilge running

Fresh-water running was observed during a real pressure-demand cycle. The bilge bits were observed during MANUAL pumping. The integration treats the bilge bits as actual-running feedback independent of mode, which is the expected architecture and a high-confidence interpretation, but an **AUTO-triggered bilge pumping capture remains a field-validation item**.

This distinction is intentional:

```text
Bilge mode=AUTO, running=0 -> armed, dry
Bilge mode=AUTO, running=1 -> automatic pumping event
Water enabled=1, running=0 -> normal/no demand
Water enabled=1, running=1 -> pump currently operating
```

## CAN command policy

### Allowed

Only `0x04001808` SFSP switch events using the captured form:

```text
press:   00 00 00 01 (key|0x80)
~150 ms
release: 00 00 00 01 key
```

### Explicitly forbidden in this implementation

- direct output forcing / source-derived `CMD_S_TOR` candidate
- blind state assumptions at startup
- automatic command retries
- bulk "turn everything off" synchronization

The steaming-light test proved why this matters: Scheiber itself applies the steaming -> navigation-light dependency. Emulating panel keys preserves that logic.

## Startup synchronization

All twelve physical outputs start `UNKNOWN`. Control writes are rejected for a channel until its physical output state has been observed.

The bridge also sends one startup batch of source-derived RTR state requests by default:

```text
02161808#R8
02181808#R8
021A1808#R8
021C1808#R8
021E1808#R8
02201808#R8
```

RTR synchronization has not yet been live-validated on this exact vessel. Failure to receive an RTR response is safe: the bridge simply remains unsynchronized for the affected outputs and waits for normal state frames.

Kill switches:

```text
SCHEIBER_SWITCH_TX=0            # no active CAN key/RTR TX
SCHEIBER_SWITCH_QUERY_STATES=0  # key TX allowed, no startup RTR queries
```

The installer defaults both to `1` for this first active-validation branch, per current test intent.

## Desired-state command logic

### Binary channels

A key pulse is sent only when:

1. actual state is known; and
2. actual state differs from desired state.

The command remains pending until the corresponding state frame confirms the requested state. Timeout is an error and **does not retry**.

### Bilge transitions

Known stable states:

```text
AUTO=0 MANUAL=0 -> OFF
AUTO=1 MANUAL=0 -> AUTO
AUTO=1 MANUAL=1 -> MANUAL
AUTO=0 MANUAL=1 -> INVALID/UNESTABLISHED
```

Planned transitions:

| From | To | Panel action |
|---|---|---|
| OFF | AUTO | AUTO key |
| AUTO | OFF | AUTO key |
| AUTO | MANUAL | MANUAL key |
| MANUAL | AUTO | MANUAL key |
| MANUAL | OFF | AUTO+MANUAL chord (observed in capture) |
| OFF | MANUAL | OFF->AUTO, confirm; then AUTO->MANUAL |

Every intermediate state must be confirmed before the next action. The controller never deliberately creates `AUTO=0/MANUAL=1`.

The exact AUTO->OFF and MANUAL->AUTO reversal behavior is strongly implied by the toggle model but should still be recorded during first controlled bilge validation.

## Anchor and freshwater AUTO semantics

AUTO is a Cerbo automation layer; these two physical Scheiber outputs are binary.

Paths:

```text
/State                  manual ON/OFF; writing exits AUTO
/Auto                   selects Cerbo automation mode
/Scheiber/AutoState     Node-RED desired physical target while Auto=1
/Status                 authoritative physical/running status
```

Entering AUTO does **not** immediately change the physical output. `/Scheiber/AutoState` is initialized to the current physical state. This prevents selecting AUTO from unexpectedly turning a light or pump on/off.

A physical Scheiber panel press on Anchor Light or Fresh Water Pump cancels Cerbo AUTO as a manual override.

### Intended Node-RED anchor flow (next phase)

```text
Auto=1
  sunset             -> AutoState=1
  sunrise + 1 hour   -> AutoState=0
  optional max-on deadline -> AutoState=0
```

Use an absolute persisted deadline rather than only an in-memory delay so a Cerbo restart cannot silently reset an eight-hour timer.

## Bilge alarms — next phase

Node-RED should watch **running feedback**, not merely mode.

Suggested initial policy:

- running 0->1 in AUTO: event/notification + runtime start
- running beyond configured warning duration: warning
- substantially longer continuous run: critical alarm
- repeated cycles inside a time window: ingress/check-bilge warning
- mode OFF + running=1: immediate anomaly
- MANUAL requested but running stays 0 after a short confirmation period: command/pump fault
- running 1->0: close event and record duration

**Do not automatically turn a bilge off because it has run too long.** Long runtime is a reason to alarm, not to stop dewatering.

## Files in this implementation

```text
cerbo/switch_protocol.py          pure protocol/state/transition model
cerbo/switch_bridge.py            D-Bus + SocketCAN + confirmation engine
cerbo/switch-service/run          independent runit service
cerbo/install_switches.sh         install/update with pinned source hashes
cerbo/uninstall_switches.sh       removal helper
tests/test_switch_protocol.py     offline state/transition tests
tests/test_switch_bridge_source.py safety/source invariants
```

## Lab/offline validation completed before PR

Run:

```bash
python3 -m py_compile cerbo/switch_protocol.py cerbo/switch_bridge.py
python3 -m unittest discover -s tests -v
sh -n cerbo/install_switches.sh cerbo/uninstall_switches.sh cerbo/switch-service/run
```

The new pure protocol tests cover:

- captured key frame generation
- paired state decoding
- all three running bits
- all 10 logical controls
- OFF/AUTO/MANUAL derivation
- invalid bilge combination rejection
- safe OFF->MANUAL two-stage path
- observed MANUAL->OFF two-key chord
- mode/running independence
- UNKNOWN state command gating
- no operational direct-output command
- no retry path
- Node-RED AutoState hook

## First vessel validation sequence

Do this with normal Scheiber network wiring intact.

1. Install/start service and inspect log; do not touch a switch yet.
2. Verify `com.victronenergy.switch.scheiber` exists and all 10 cards appear in GX Switch UI.
3. Verify physical panel changes are mirrored correctly in GX.
4. Check `/Scheiber/AllOutputsSynchronized` and individual `/Scheiber/Synchronized` paths.
5. Confirm the startup RTR request produces state frames; record a new candump. If not, leave the bridge listening passively and document the result.
6. **First active command: Deck Floodlight or General Lighting only.** Command ON from GX, verify exactly one key press/release is transmitted, physical light changes, state feedback confirms, and physical panel indication follows.
7. Command the same light OFF and verify the reverse path.
8. Test Navigation/Steaming and confirm Scheiber still applies steaming -> navigation dependency naturally.
9. Test Anchor OFF/ON, then enter AUTO and verify entering AUTO does not alter physical state. Write `/Scheiber/AutoState` manually to verify automatic target control.
10. Test Fresh Water Pump enable/disable and confirm `/Status`/`Running` follows actual demand independently.
11. Only now test bilges, one side at a time, with safe observation and candump recording:
    - OFF -> AUTO -> OFF
    - AUTO -> MANUAL -> AUTO
    - MANUAL -> OFF
    - OFF -> MANUAL (must pass through confirmed AUTO)
12. Safely trigger an **AUTO bilge pumping cycle** and prove bit `0x02`/`0x04` follows actual motor operation without mode changing.
13. Preserve every active validation capture with exact operator annotations and hashes.

## Acceptance criteria before merging/production use

- no unrequested CAN key frames at idle
- no command while physical state is UNKNOWN
- one action per desired-state difference; no blind retries
- feedback rollback after failed confirmation
- physical panel remains fully functional
- steaming/navigation interlock remains Scheiber-owned
- no transition through bilge `AUTO=0/MANUAL=1`
- AUTO bilge running feedback field-confirmed
- Cerbo reboot returns safely and resynchronizes without changing outputs
- TX kill switch proven

## Future handover notes

The most important invariant is **requested state is not physical truth**. `/State` is a request/UI state; Scheiber `02xx1808` output frames and `0x02141808` running bits remain authoritative. Do not simplify the bridge into "write button -> assume state".

If the GUI behavior of Type 9 evolves, preserve the hardware model first. The D-Bus presentation can change without changing the CAN transition engine.
