# 14. Reproduction and validation plan

## 14.1 Friend-reproducible experiment

18. Photograph and label the Scheiber connector, bus location, and SH-C30A switch positions.

19. Power off and measure CAN-H to CAN-L termination resistance.

20. Wire Scheiber pin 5 to CAN_H, pin 6 to CAN_L, and verified ground to GND. Leave recovery and +12 V unconnected.

21. Connect the SH-C30A to the Raspberry Pi and verify a native SocketCAN interface.

22. Bring the interface up at 250 kbit/s and confirm ERROR-ACTIVE with clean counters.

23. Start candump -L and record an untouched baseline.

24. Perform one labelled action at a time, waiting for stabilization.

25. Stop the log, calculate SHA-256, copy the exact system configuration, and run the analyzer.

26. Compare output CSVs and event timeline against the report examples.

27. Keep all transmission disabled until receive-only results are repeatable.

## 14.2 Highest-priority validation tests

| **Priority** | **Test**                                                                  | **Result expected**                                           |
|--------------|---------------------------------------------------------------------------|---------------------------------------------------------------|
| 1            | Verify charger nameplates and independently disable one charger at a time | Confirm 60 A / 40 A / 25 A node assignments and physical role |
| 2            | Apply known small load to each house battery one at a time                | Assign six physical batteries to six CAN IDs                  |
| 3            | Clamp-meter stepped charge/discharge current                              | Calibrate 0x4E00-offset current field                         |
| 4            | Long discharge plus separate temperature perturbation                     | Distinguish SoC from temperature in field 3                   |
| 5            | Load/start port, starboard, and generator batteries separately            | Locate the three starter-battery streams                      |
| 6            | Repeat exact generator/panel sequence with timestamped markers            | Validate 0x02140898 ramp-marker meaning and direct-command safety/companion-frame behavior |
| 7            | Refill/drain known tank volumes                                           | Confirm linear percent-to-litre calibration and fourth word   |

## 14.3 Acceptance criteria

Promote a field to confirmed only after at least two repeatable controlled transitions, agreement with an independent instrument, stable datatype/endianness/scale, a documented unavailable encoding, and no contradictory values elsewhere in the capture.

