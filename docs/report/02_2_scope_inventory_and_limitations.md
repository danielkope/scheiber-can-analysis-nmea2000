# 2. Scope, inventory, and limitations

## 2.1 Installation inventory

| **Item**                | **Known quantity** | **CAN status**                                                    |
|-------------------------|--------------------|-------------------------------------------------------------------|
| House batteries         | 6                  | Six individual candidate streams found; physical order unresolved |
| Engine-start batteries  | 2                  | Port and starboard; no clean independent IDs yet                  |
| Generator-start battery | 1                  | Likely charged by 25 A family, not proven                         |
| Battery chargers        | 3                  | 60 A, 40 A, 25 A signatures                                       |
| Water tank              | 1 x 600 L          | Level confirmed                                                   |
| Diesel tanks            | 2 x 500 L          | Levels confirmed                                                  |
| Source panels           | AC and House       | Request/applied states confirmed                                  |
| Generator               | 1                  | Direct START/STOP command semantics confirmed; AC telemetry observed |

## 2.2 Operator action order

1. Generator ON: `02460B88#01`.
2. AC panel: Generator to OFF.
3. AC panel: OFF to Shore.
4. AC panel: Shore to Generator.
5. House panel: Generator to OFF.
6. House panel: OFF to Shore.
7. House panel: Shore to Generator.
8. Generator OFF: `02460B88#02`.

The source selector request/applied sequence aligns cleanly with this order. The generator/AC module additionally shows four directional ramp markers on 0x02140898. These are separate from the direct command frame and appear to describe AC ramp direction or source transitions rather than command intent.

## 2.3 Limitations

- Only one short capture was available; many physical values changed together during source transfers.
- No independent multimeter, clamp-ammeter, temperature, or frequency reference was logged alongside the CAN timestamps.
- Physical battery and charger wiring labels were not available in the dump.
- No Scheiber proprietary protocol specification was provided.
- The SH-C30A is non-isolated; it is acceptable for a short supervised diagnostic capture but an isolated CAN interface is preferable for permanent marine installation.
- Although generator command semantics are confirmed, safe transmit behavior is not: companion frames, acknowledgement, timing, retries, interlocks, and fail-safe behavior need controlled validation.
