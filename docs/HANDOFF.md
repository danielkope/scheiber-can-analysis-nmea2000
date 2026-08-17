# Future-engineer handoff

## Evidence package

- Raw capture: `data/raw/d5175281-0a41-493a-ae0d-fb84baba6d2f.log.xz` (extract before analysis)
- SHA-256 of uncompressed capture: `47296d01c77acc01bc32621e8b0bbdb7c6f7e4837da1c207342baba30a281641`
- Capture size: 207,809 bytes
- Frames: 4,401
- Parse errors: 0
- Unique extended CAN IDs: 45
- Duration: 228.962155 seconds
- UTC interval: 2026-08-17 15:13:45.028287 to 15:17:33.990442
- Vienna local interval: 2026-08-17 17:13:45.028287 to 17:17:33.990442 CEST

## Operator-reported system

- Six house batteries.
- Two engine-start batteries: port and starboard.
- One generator-start battery.
- Three battery chargers; two participate in house/engine charging, one charges the generator battery.
- Water tank: 600 L.
- Diesel tank 1: 500 L.
- Diesel tank 2: 500 L.
- Two source-selection panels: AC and House.

## Operator action order represented in the capture

1. Generator ON.
2. AC panel: Generator -> OFF.
3. AC panel: OFF -> Shore.
4. AC panel: Shore -> Generator.
5. House panel: Generator -> OFF.
6. House panel: OFF -> Shore.
7. House panel: Shore -> Generator.
8. Generator OFF.

The request/applied selector sequence is well supported. Four `0x02140898` frames are AC ramp-direction markers and are not direct generator commands.

## Confirmed generator lifecycle

### External START

```text
02460B88#01                 -> STARTING
02440B88#02/#03             -> STARTING confirmed
005A1020 first LE word 500  -> 50.0 Hz -> RUNNING
02440B88#01                 -> RUNNING_SETTLED
```

Baseline evidence:

| Line | Relative time | Frame | State after |
|---:|---:|---|---|
| 885 | 49.658548 s | `02460B88#01` | STARTING |
| 887 | 49.666932 s | `02440B88#02` | STARTING |
| 899 | 50.368585 s | `02440B88#03` | STARTING |
| 931 | 52.162626 s | `02440B88#02` | STARTING |
| 1086 | 58.540249 s | `005A1020#F401FFFFFFFFFFFF` | RUNNING |
| 1102 | 59.092541 s | `02440B88#03` | RUNNING; lingering STARTING status does not regress state |
| 1544 | 79.600994 s | `02440B88#01` | RUNNING_SETTLED |

### External STOP

```text
02460B88#02                 -> STOPPING
02440B88#05/#04             -> STOPPING confirmed
005A1020 first LE word 0    -> 0.0 Hz -> STOPPED
02440B88#00                 -> OFF_IDLE
```

Baseline evidence:

| Line | Relative time | Frame | State after |
|---:|---:|---|---|
| 3427 | 177.378315 s | `02460B88#02` | STOPPING |
| 3429 | 177.386191 s | `02440B88#05` | STOPPING |
| 3436 | 177.641176 s | `02440B88#04` | STOPPING |
| 3451 | 178.151463 s | `005A1020#9001FFFFFFFFFFFF` | STOPPING; 40.0 Hz decay |
| 3499 | 179.661780 s | `005A1020#0000FFFFFFFFFFFF` | STOPPED |

`02440B88#00` was confirmed in follow-on work but is absent from the baseline file. Do not claim that the supplied capture reaches `OFF_IDLE`; its reconstructed final state is `STOPPED`.

### Frequency context guard

`0x005A1020` also changes when the associated AC path is switched. The baseline contains 0 Hz before the STOP command and 50 Hz later without a new START command. Therefore:

- 50 Hz means `RUNNING` only during an active START transaction.
- 0 Hz means `STOPPED` only during an active STOP transaction.
- Outside those contexts, record AC present/absent and leave engine state unchanged.

This rule is implemented in `scripts/generator_state_machine.py` and is essential to avoid false generator lifecycle events during panel switching.

## Highest-value results

1. Tank levels and capacities are ready for NMEA 2000 PGN 127505 translation.
2. Both source selectors and their request/applied distinction are decoded.
3. AC voltage and frequency are decoded for the `0x0898` module.
4. Direct generator command, lifecycle/status enum, and context-gated frequency progression are decoded.
5. Six individual house-battery voltage streams are identified.
6. The house-battery current field has an exact signed zero offset (`0x4E00`); only physical scale remains.
7. Three charger device families are identified, with credible 12 V / 60 A, 12 V / 40 A, and 12 V / 25 A signatures.
8. Charger AC input voltage and frequency fields are strong candidates.
9. Physical port/starboard/generator battery assignments remain unresolved and require controlled loads.

## Analyzer and outputs

```bash
xz -dc data/raw/d5175281-0a41-493a-ae0d-fb84baba6d2f.log.xz > /tmp/scheiber.log
python3 scripts/scheiber_can_analyze.py /tmp/scheiber.log \
  --config config/system_config.json \
  --output analysis-output
```

Key outputs:

- `generator_state_timeline.csv`: chronological, context-aware generator state reconstruction.
- `event_candidates.csv`: command, status, transition-marker, frequency, and panel events.
- `decoded_fields_long.csv`: all decoded fields with datatype, unit, endian, scale, confidence, and status.
- `capture_metadata.json`: hash and capture metadata.
- `summary.md`: human-readable summary.

## Do not assume

- Do not assume CAN ID order equals physical battery order.
- Do not assume the 25 A charger role is proven solely from its rating.
- Do not assume house-battery field 3 is SoC rather than temperature until tested.
- Do not use `0x02140898` as the generator START/STOP command.
- Do not use `0x005A1020` frequency alone as global engine state; source switching affects it.
- Do not assume `0x02440B88#02/#03` or `#05/#04` exact substage meanings beyond STARTING/STOPPING.
- Although command and receive-side lifecycle semantics are confirmed, do not assume replay is safe without validating companion frames, timing, acknowledgements, retries, interlocks, aborts, and fail-safe behavior.
- Do not connect Scheiber CAN and NMEA 2000 as one electrical bus.

## Next recommended experiment

The highest-value next capture is a labelled, one-variable-at-a-time run that records:

- multiple complete START and STOP cycles, including the final `02440B88#00`;
- every adjacent `0x02160B88` and `0x02140B88` companion frame;
- exact button press, crank start, AC-present, settled-running, stop request, AC-loss, engine-stop, and idle timestamps;
- each of the six house batteries with a known small load;
- port, starboard, and generator battery voltages under distinct loads;
- each charger independently disabled/enabled.
