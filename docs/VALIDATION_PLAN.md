# Controlled validation plan

## Objective

Convert the current mapping from engineering hypotheses into calibration-grade definitions without risking generator, shore-power, or battery systems.

## Ground rules

- Use passive logging first.
- Change one physical variable at a time.
- Keep a timestamped experiment notebook.
- Use calibrated meters for voltage, current, temperature, and frequency.
- Do not transmit proprietary frames until receive-only mappings are independently confirmed.
- Treat generator and source-switching work as safety-critical electrical testing.

## A. Tank calibration

1. Record stable baseline percentages and physical dip/gauge readings.
2. Add or remove a known volume.
3. Capture at least five minutes before and after.
4. Fit percentage against litres and check hysteresis, damping, and clipping.
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

## E. Panel and generator lifecycle validation

Repeat the known panel sequence with exact event markers:

1. Generator ON.
2. AC panel: Generator -> OFF.
3. AC panel: OFF -> Shore.
4. AC panel: Shore -> Generator.
5. House panel: Generator -> OFF.
6. House panel: OFF -> Shore.
7. House panel: Shore -> Generator.
8. Generator OFF.

For at least three independent generator cycles, record these physical timestamps:

- START button/command issued;
- starter/crank begins;
- engine fires;
- AC frequency first becomes nonzero;
- AC reaches 50 Hz;
- display/controller reports stable running;
- STOP button/command issued;
- AC begins decaying;
- AC reaches 0 Hz;
- engine audibly stops;
- final idle indication appears.

Expected receive-side sequence:

```text
02460B88#01 -> STARTING
02440B88#02/#03 -> STARTING confirmed
005A1020=50.0 Hz -> RUNNING
02440B88#01 -> RUNNING_SETTLED

02460B88#02 -> STOPPING
02440B88#05/#04 -> STOPPING confirmed
005A1020=0.0 Hz -> STOPPED
02440B88#00 -> OFF_IDLE
```

### Required checks

1. Confirm whether `#02` always precedes `#03`, and whether either value repeats.
2. Confirm whether `#05` always precedes `#04`, and whether either value repeats.
3. Determine the delay distributions from command to status, status to 50/0 Hz, and frequency milestone to terminal status.
4. Capture the final `02440B88#00` at least twice.
5. Correlate `0x02160B88`, `0x02140B88`, and all adjacent companion frames with each transition.
6. Repeat source-panel switching while the generator state is fixed to verify that context gating prevents false state transitions.
7. Verify that 50 Hz outside START and 0 Hz outside STOP are logged as AC-path observations rather than generator engine-state changes.

### Transmission prerequisites

Before any transmit implementation, validate on an isolated test setup:

- required companion frames and ordering;
- repetition rate and command duration;
- positive and negative acknowledgements;
- command timeout and watchdog behavior;
- crank limits and retry policy;
- low-voltage, oil-pressure, temperature, fire, exhaust, shore-power, and transfer-switch interlocks;
- abort behavior during STARTING and STOPPING;
- fail-safe STOP behavior after CAN loss, gateway crash, or power interruption.

The present repository intentionally implements no command transmitter.

## F. Acceptance criteria

A field becomes `confirmed` only after:

- at least two repeatable controlled transitions;
- correct direction, scale, and offset against an independent instrument;
- stable endianness and datatype interpretation;
- no contradictory values elsewhere in the capture;
- a documented unavailable/error encoding.

A lifecycle transition additionally requires:

- the correct transaction context;
- ordered physical correlation;
- no false transition during source-panel-only operations;
- documented handling of late or repeated status frames.
