# Controlled validation plan

## Objective

Convert the current mapping from engineering hypotheses into calibration-grade definitions without risking generator, shore-power, or battery systems.

## Ground rules

- Use passive logging first.
- Change one physical variable at a time.
- Keep a timestamped experiment notebook.
- Use calibrated meters for voltage, current, temperature, and frequency.
- Do not transmit proprietary frames until receive-only mappings are independently confirmed.

## A. Tank calibration

1. Record stable baseline percentages and physical dip/gauge readings.
2. Add or remove a known volume.
3. Capture at least five minutes before and after.
4. Fit percentage against litres and check for hysteresis, damping, and clipping.
5. Repeat at low, mid, and high tank levels.

Expected result: confirm `0x02040580` as linear percent and determine whether the fourth word is quality, sequence, or alarm state.

## B. Six house-battery physical assignment

For each physical house battery, one at a time:

1. Record all six `0x060x0580` streams.
2. Apply a small, known, separately fused load to that battery or temporarily isolate its sensor according to safe service procedures.
3. Observe which CAN ID changes first and most strongly.
4. Repeat twice and label the physical battery position.

Then calibrate current:

1. Use a DC clamp meter.
2. Apply stepped loads, for example 0 A, 2 A, 5 A, and 10 A where safe.
3. Regress measured current against `u16LE(bytes 2-3) - 0x4E00`.
4. Verify sign under charging and discharging.

Distinguish field 3:

- Let SoC change over several hours while temperature remains stable.
- Separately warm one sensor slightly and safely while SoC is stable.
- The field that follows the manipulated variable determines whether 72-74 is SoC, degF temperature, or another quantity.

## C. Port, starboard, and generator-start batteries

The current capture does not expose three clean independent starter-battery sensor IDs. Test each battery separately:

1. Measure the battery voltage with a multimeter.
2. Apply a brief safe load appropriate to that battery.
3. Observe all charger families and unresolved DC frames.
4. Start only the corresponding engine/generator where safe and record alternator charging response.

Candidate priority:

- `0x1020` / 12 V 25 A charger family is the best generator-start charger candidate.
- `0x1008` / 60 A and `0x1010` / 40 A are likely house/engine charging devices.
- Exact charger-to-port/starboard/house wiring remains unconfirmed.

## D. Charger calibration

For each charger, independently switch it off or disconnect AC input according to the manufacturer's procedure.

Measure and correlate:

| Candidate field | Instrument |
|---|---|
| `0x005010xx` bytes 0-1 x0.1 | DC voltmeter |
| `0x005010xx` bytes 2-3 x0.1 | DC clamp ammeter |
| `0x005010xx` bytes 4-5 x0.1 | true-RMS AC voltmeter |
| `0x005A10xx` bytes 0-1 x0.1 | frequency meter |
| `0x005610xx` byte 4/5 | charger nameplate nominal V/A |
| `0x005210xx` bytes 2-3 | temperature probe and elapsed-time comparison |

Change one charger configuration setting at a time to decode the sparse `0x005410xx` messages.

## E. Panel and generator sequence

Repeat the known sequence with exact event markers:

1. Generator ON.
2. AC panel: Generator -> OFF.
3. AC panel: OFF -> Shore.
4. AC panel: Shore -> Generator.
5. House panel: Generator -> OFF.
6. House panel: OFF -> Shore.
7. House panel: Shore -> Generator.
8. Generator OFF.

Record both the button action and visible applied state. Direct command semantics are confirmed as `0x02460B88#01=START` and `0x02460B88#02=STOP`. The separate `0x02140898` frames remain AC ramp-direction markers. Before any transmit implementation, validate required companion frames, message ordering, repetition rate, acknowledgements, timeout behavior, interlocks, abort behavior, and fail-safe STOP on an isolated test setup.

## F. Acceptance criteria

A field becomes `confirmed` only after:

- at least two repeatable controlled transitions;
- correct direction, scale, and offset against an independent instrument;
- stable endianness and datatype interpretation;
- no contradictory values elsewhere in the capture;
- a documented unavailable/error encoding.
