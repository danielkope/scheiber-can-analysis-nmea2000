# Future-engineer handoff

## Evidence package

- Raw capture: `data/raw/d5175281-0a41-493a-ae0d-fb84baba6d2f.log.xz` (extract before analysis)
- SHA-256: `47296d01c77acc01bc32621e8b0bbdb7c6f7e4837da1c207342baba30a281641`
- Capture size: 207,809 bytes
- Frames: 4,401
- Parse errors: 0
- Unique extended CAN IDs: 45
- Duration: 228.962155 seconds
- UTC interval: 2026-08-17 15:13:45.028287 to 15:17:33.990442
- Vienna local interval: 2026-08-17 17:13:45.028287 to 17:17:33.990442 (CEST)

## Operator-reported system

- Six house batteries.
- Two engine-start batteries: port and starboard.
- One generator-start battery.
- Three battery chargers; two participate in house/engine charging, one charges the generator battery.
- Water tank 600 L.
- Diesel tank 1 500 L.
- Diesel tank 2 500 L.
- Two source-selection panels: AC and House.

## Operator action order represented in the capture

1. Generator ON.
2. AC panel Generator -> OFF.
3. AC panel OFF -> Shore.
4. AC panel Shore -> Generator.
5. House panel Generator -> OFF.
6. House panel OFF -> Shore.
7. House panel Shore -> Generator.
8. Generator OFF.

The request/applied selector sequence is well supported. Direct generator command semantics are confirmed as `0x02460B88#01=START` and `0x02460B88#02=STOP`. Four additional `0x02140898` frames are AC ramp-direction markers and are not direct commands.

## Highest-value results

1. Tank levels and capacities are ready for NMEA 2000 PGN 127505 translation.
2. Both source selectors and their request/applied distinction are decoded.
3. AC voltage and frequency are decoded for the `0x0898` module.
4. Six individual house-battery voltage streams are identified.
5. The house-battery current field has an exact signed zero offset (`0x4E00`); only physical scale remains.
6. Three charger device families are identified, with credible 12 V / 60 A, 12 V / 40 A, and 12 V / 25 A signatures.
7. Charger AC input voltage and frequency fields are strong candidates.
8. Generator command `0x02460B88` is confirmed: `0x01=START`, `0x02=STOP`.
9. Physical port/starboard/generator battery assignments remain unresolved and require controlled loads.

## Do not assume

- Do not assume CAN ID order equals physical battery order.
- Do not assume the 25 A charger role is proven solely from its rating.
- Do not assume house-battery field 3 is SoC rather than temperature until tested.
- `0x02140898` remains a transition marker, not the direct command frame.
- Although `0x02460B88#01/#02` semantics are confirmed, do not assume replay is safe without validating companion frames, timing, acknowledgements, retries, interlocks, and fail-safe behavior.
- Do not connect Scheiber CAN and NMEA 2000 as one electrical bus.

## Next recommended experiment

The single most useful next capture is a labelled, one-variable-at-a-time run that measures:

- each of the six house batteries with a known small load;
- port, starboard, and generator battery voltages under distinct loads;
- each charger independently disabled/enabled;
- the complete generator and two-panel source sequence with exact timestamps.
