# 14. Reproduction and validation plan

## 14.1 Friend-reproducible experiment

1. Photograph and label the Scheiber connector, bus location, and SH-C30A switch positions.
2. Power off and measure CAN-H to CAN-L termination resistance.
3. Wire Scheiber pin 5 to CAN_H, pin 6 to CAN_L, and verified ground to GND. Leave recovery and +12 V unconnected.
4. Connect the SH-C30A to the Raspberry Pi and verify a native SocketCAN interface.
5. Bring the interface up at 250 kbit/s and confirm `ERROR-ACTIVE` with clean counters.
6. Start `candump -L` and record an untouched baseline.
7. Perform one labelled action at a time, waiting for stabilization.
8. Stop the log, calculate SHA-256, copy the exact system configuration, and run the analyzer.
9. Compare output CSVs and event timeline against the report examples.
10. Keep all transmission disabled until receive-only results are repeatable.

## 14.2 Generator lifecycle reproduction

For at least three cycles, record the exact physical time of:

- START action;
- crank onset;
- engine firing;
- first nonzero frequency;
- 50 Hz;
- stable-running indication;
- STOP action;
- frequency decay;
- 0 Hz;
- engine stopped;
- idle indication.

The expected receive-side progression is:

```text
02460B88#01 -> STARTING
02440B88#02/#03 -> STARTING confirmed
005A1020 word 0 = 500 -> 50.0 Hz -> RUNNING
02440B88#01 -> RUNNING_SETTLED

02460B88#02 -> STOPPING
02440B88#05/#04 -> STOPPING confirmed
005A1020 word 0 = 0 -> 0.0 Hz -> STOPPED
02440B88#00 -> OFF_IDLE
```

The baseline file contains every milestone except the final `02440B88#00`. The analyzer therefore ends that capture at `STOPPED`. Capture `#00` twice before treating its timing as characterized.

Frequency must remain context-gated: panel source changes also cause `0x005A1020` to move between 0 and 50 Hz. The state machine only treats 50 Hz as `RUNNING` during START and 0 Hz as `STOPPED` during STOP.

## 14.3 Highest-priority validation tests

| **Priority** | **Test** | **Result expected** |
|---:|---|---|
| 1 | Repeat complete generator START/STOP cycles with physical timestamp markers | Confirm lifecycle order, delays, repeats, and final `OFF_IDLE` |
| 2 | Capture adjacent `0x02160B88` and `0x02140B88` frames | Determine companion, acknowledgement, or interlock roles |
| 3 | Switch AC/House sources without changing generator engine state | Verify no false lifecycle transitions from frequency-only changes |
| 4 | Verify charger nameplates and independently disable one charger at a time | Confirm 60 A / 40 A / 25 A node assignments and physical role |
| 5 | Apply known small load to each house battery one at a time | Assign six physical batteries to six CAN IDs |
| 6 | Clamp-meter stepped charge/discharge current | Calibrate `0x4E00`-offset current field |
| 7 | Long discharge plus separate temperature perturbation | Distinguish SoC from temperature in field 3 |
| 8 | Load/start port, starboard, and generator batteries separately | Locate the three starter-battery streams |
| 9 | Refill/drain known tank volumes | Confirm linear percent-to-litre calibration and fourth word |

## 14.4 Acceptance criteria

Promote a field to confirmed only after at least two repeatable controlled transitions, agreement with an independent instrument, stable datatype/endianness/scale, a documented unavailable encoding, and no contradictory values elsewhere in the capture.

Promote a generator lifecycle rule only when:

- command, status, and physical milestone occur in the expected order;
- repeated/late status frames are handled without state regression;
- panel source switching cannot create a false engine-state transition;
- final terminal state is independently observed;
- failure and abort cases are documented.
