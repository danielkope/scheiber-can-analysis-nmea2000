# Scheiber CAN analysis summary

- Source: `d5175281-0a41-493a-ae0d-fb84baba6d2f.log`
- SHA-256: `47296d01c77acc01bc32621e8b0bbdb7c6f7e4837da1c207342baba30a281641`
- Frames: 4,401
- Unique CAN IDs: 45
- Parse errors: 0
- Duration: 228.962155 s
- Capture interface: `can1`
- Scheiber bitrate: 250,000 bit/s

## Tank readings

| Tank | Level | Capacity | Derived volume |
|---|---:|---:|---:|
| Water | 84% | 600 L | 504 L |
| Diesel 1 | 63% | 500 L | 315 L |
| Diesel 2 | 79% | 500 L | 395 L |

## Confirmed generator lifecycle mapping

### START

```text
02460B88#01                 -> STARTING
02440B88#02/#03             -> STARTING confirmed
005A1020 word 0 = 500       -> 50.0 Hz -> RUNNING
02440B88#01                 -> RUNNING_SETTLED
```

### STOP

```text
02460B88#02                 -> STOPPING
02440B88#05/#04             -> STOPPING confirmed
005A1020 word 0 = 0         -> 0.0 Hz -> STOPPED
02440B88#00                 -> OFF_IDLE
```

`02440B88#00` is confirmed from follow-on work but is absent from this baseline capture. The baseline reconstructed final state is therefore `STOPPED`.

## Baseline lifecycle events

| Line | t (s) | Frame | Result |
|---:|---:|---|---|
| 885 | 49.658548 | `02460B88#01` | STARTING |
| 887 | 49.666932 | `02440B88#02` | STARTING confirmed |
| 899 | 50.368585 | `02440B88#03` | STARTING confirmed |
| 931 | 52.162626 | `02440B88#02` | STARTING confirmed |
| 1086 | 58.540249 | `005A1020#F401FFFFFFFFFFFF` | 50.0 Hz -> RUNNING |
| 1102 | 59.092541 | `02440B88#03` | lingering STARTING; retain RUNNING |
| 1544 | 79.600994 | `02440B88#01` | RUNNING_SETTLED |
| 2754 | 145.475456 | `005A1020#0000FFFFFFFFFFFF` | 0 Hz outside STOP; context-only |
| 3231 | 167.702140 | `005A1020#F401FFFFFFFFFFFF` | 50 Hz outside START; context-only |
| 3427 | 177.378315 | `02460B88#02` | STOPPING |
| 3429 | 177.386191 | `02440B88#05` | STOPPING confirmed |
| 3436 | 177.641176 | `02440B88#04` | STOPPING confirmed |
| 3451 | 178.151463 | `005A1020#9001FFFFFFFFFFFF` | 40.0 Hz decay |
| 3499 | 179.661780 | `005A1020#0000FFFFFFFFFFFF` | 0.0 Hz -> STOPPED |

## Context rule

The `0x005A1020` frequency field is affected by AC source switching. The state tracker therefore only promotes 50 Hz to `RUNNING` during START and 0 Hz to `STOPPED` during STOP. Outside those transactions it records AC present/absent without changing generator engine state.

## Interpretation policy

- `confirmed`: directly correlated with known operator state or an unambiguous physical scale.
- `candidate`: strong engineering inference but needs controlled validation.
- `guess`: useful working hypothesis only.
- `unresolved`: preserved raw without invented semantics.

Generator and source-control transmission remain disabled.
