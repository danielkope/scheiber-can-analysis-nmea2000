# Future-agent handoff — Scheiber V8 control panel

## Start here

Canonical section: `docs/control-panel-v8/README.md`.

Do not merge this work conceptually with the generator/source-selector control paths unless the CAN evidence explicitly requires it. This panel is a separate `RefBloc=48, Coding=1, Subnetwork=0` device family on the same Multibloc V8 network.

Reported panel markings:

```text
SCHEIBER 41.96012.01 000000
V08.15.01 000276 756-20
```

## Non-negotiable physical prerequisite

**The panel must be connected by its normal physical Scheiber X1/X2 cable into the rest of the working Multibloc V8 network before reproducing the captures or testing control.**

The complete network supplies the real outputs, feedback, interlocks, termination, and distributed logic. A disconnected panel plus USB-CAN adapter is not an equivalent test setup.

## Immutable evidence

```text
data/raw/control-panel-v8/panel-switch-sequence-2026-08-18.log
SHA-256 bf035f80627716379f7ea0618ae4f657cd6d82ab84c750f1492176c55c9793f7

data/raw/control-panel-v8/water-pump-demand-2026-08-18.log
SHA-256 43feb9b8008e7348a8ca32af723802b2396fac0aee9cbfae46ce5f8664feb875

docs/control-panel-v8/control-panel-reference.webp
SHA-256 eef58d0f7a594cf7aa7d7546d4deec34d4b2d158067cddc744772a2a35fa0bc2
```

Do not edit those files. Add new captures instead.

## Independent protocol source used

Pinned source:

```text
https://github.com/domoticz/domoticz/blob/11d95f0c7afedabc6b4c6fef2de971eecd9ee278/hardware/USBtin_MultiblocV8.cpp
```

Use this exact revision when checking the reasoning recorded in this section. Important source concepts: Multibloc CAN-ID masks/shifts, `SFSP_SWITCH=512`, `E_TOR=266`, paired output-state types `267..`, press bit `0x80`, state flags in bytes 2/6, and RTR state requests.

## What is established

Panel ALIVE:

```text
00001808#080F018076
firmware 08.15.01
configuration CRC 0x8076
RefBloc 48 / Coding 1 / Subnetwork 0
```

Button event CAN ID:

```text
04001808
payload 00 00 00 01 KK
KK bit 0x80 set = press
same key with 0x80 clear = release
```

Key/output map:

```text
02 electronics             -> output 1
05 deck floodlight          -> output 2
03 navigation lights        -> output 3
06 anchor light             -> output 4
04 steaming light           -> output 5
08 port bilge AUTO          -> output 6
0C port bilge MANUAL        -> output 7
09 starboard bilge AUTO     -> output 8
0D starboard bilge MANUAL   -> output 9
0A fresh-water pump enable  -> output 10
0B fridge                   -> output 11
07 general/cabin lighting   -> output 12
```

State IDs:

```text
02161808 outputs 1-2
02181808 outputs 3-4
021A1808 outputs 5-6
021C1808 outputs 7-8
021E1808 outputs 9-10
02201808 outputs 11-12
```

For each state frame:

```text
slot 1: level byte 0, command flags byte 2, ON bit 0x01
slot 2: level byte 4, command flags byte 6, ON bit 0x01
```

Do not decode bytes 1/3/5/7 without new evidence.

Digital-input feedback:

```text
02141808#01 fresh-water pump actually running / demand active
02141808#02 port bilge running
02141808#04 starboard bilge running
02141808#00 none of those running
```

The frame class `E_TOR` is source-established. The bit-to-function mapping is a high-confidence inference from controlled tests, not an OEM label.

Steaming dependency is observed:

```text
steaming ON -> steaming output 5 ON + navigation output 3 ON
steaming OFF -> output 5 OFF; output 3 remains ON
```

## Crucial toggle/state rule

Never initialize software state to OFF.

The physical key is a momentary event. It does not encode explicit ON or OFF. At controller startup:

```text
all functions = UNKNOWN
```

Then learn/request actual state from the paired state frames. A desired-state controller only presses a key if actual state is known and differs from desired state.

Never turn everything OFF merely to establish a baseline. That is particularly unacceptable for bilge AUTO modes.

## Active-control status

External injection on this exact installation is still pending live validation.

A captured/source-consistent fridge event is:

```bash
cansend can1 04001808#000000018B
sleep 0.15
cansend can1 04001808#000000010B
```

`scripts/scheiber_v8_panel.py` is dry-run by default and requires `--transmit` for active CAN.

Do the first active test on a non-critical lighting circuit, not a bilge function.

## Startup state synchronization candidate

The pinned Multibloc V8 source requests digital-output state with CAN RTR. Candidate exact requests for this panel are:

```bash
cansend can1 02161808#R8
cansend can1 02181808#R8
cansend can1 021A1808#R8
cansend can1 021C1808#R8
cansend can1 021E1808#R8
cansend can1 02201808#R8
```

This mechanism is source-derived but has not yet been live-validated on the supplied installation. Record a new capture when testing it.

## Do not use direct output command as the first control method

The source includes `type_CMD_S_TOR=283`, implying direct output command ID `0x02361808` for this panel's base fields. Do not operationalize this yet.

Reason: it may bypass Scheiber logic/interlocks, and the steaming/navigation behavior proves those interlocks are meaningful. Keep the direct-output path documented as source-derived/unvalidated unless separately tested with a safety plan.

## Other frames to preserve as unresolved

```text
02041808  E_ANA_1_TO_4, frequently changing, function unresolved
04081808  SFSP_SYNCHRO, correlated with some button presses
04020000  SFSP_LED_CMD, FFFF1111... / FFFF2222... around navigation changes
```

Do not assign new semantics from timing alone.

## Next validation sequence

1. Connect panel normally to the complete Scheiber network.
2. Passive `candump -L` and live decoder first.
3. Validate RTR output-state synchronization.
4. Validate one external button injection on general lighting/deck floodlight.
5. Verify output state and physical panel indicator confirmation.
6. Repeat once to prove toggle reversal.
7. Build desired-state controller using `UNKNOWN -> synchronized ON/OFF` semantics.
8. Only after state synchronization/control is robust, consider bilge-mode integration.
9. For bilges, explicitly model OFF/AUTO/MANUAL; do not flatten to a boolean.
10. Keep every active test capture with exact operator action annotations.

## Regression command

```bash
python3 scripts/scheiber_v8_panel.py --log data/raw/control-panel-v8/panel-switch-sequence-2026-08-18.log >/tmp/panel.decoded
python3 -m unittest tests.test_control_panel
```
