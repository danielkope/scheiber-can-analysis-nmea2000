# Scheiber CAN mapping register

> Status labels are intentional. The original passive capture is preserved as evidence; follow-on live tests are called out separately. Generator START/STOP transmission is validated only for the specific installation described here. AC/House source-selection transmission remains disabled.

## Confirmed / high-confidence mappings

| CAN ID | Bytes | Signal | Type / endian | Scale / enum | Current status |
|---|---|---|---|---|---|
| `0x02040580` | 0-1 | Fresh-water level | `uint16` BE | x1 % | confirmed |
| `0x02040580` | 2-3 | Diesel tank 1 level | `uint16` BE | x1 % | confirmed |
| `0x02040580` | 4-5 | Diesel tank 2 level | `uint16` BE | x1 % | confirmed |
| derived | n/a | Fresh-water remaining | derived | 600 L x level/100 | confirmed capacity + confirmed level |
| derived | n/a | Diesel 1 remaining | derived | 500 L x level/100 | confirmed capacity + confirmed level |
| derived | n/a | Diesel 2 remaining | derived | 500 L x level/100 | confirmed capacity + confirmed level |
| `0x02420B90` | 0 | AC-panel requested source | `uint8 enum` | `01=OFF,02=SHORE,04=GENERATOR` | confirmed semantics; bridge never transmits |
| `0x02400B90` | 0 | AC-panel applied source | `uint8 enum` | same | confirmed; bridge receive-only |
| `0x02420B88` | 0 | House-panel requested source | `uint8 enum` | same | confirmed semantics; bridge never transmits |
| `0x02400B88` | 0 | House-panel applied source | `uint8 enum` | same | confirmed; bridge receive-only |
| `0x02040B90` | 4-5 | AC-panel voltage | `uint16` BE | x1 V | confirmed |
| `0x02040B88` | 4-5 | House-panel voltage | `uint16` BE | x1 V | confirmed |
| `0x02460B88` | 0 | Generator command | `uint8 enum` | `01=START,02=STOP` | confirmed; both payloads live-tested TX |
| `0x02440B88` | 0 | Generator lifecycle | `uint8 enum` | `00=OFF_IDLE,01=RUNNING_SETTLED,02/03=STARTING,04/05=STOPPING` | confirmed grouping |
| `0x005A1020` | 0-1 | Generator-specific frequency | `uint16` LE | x0.1 Hz | confirmed physical field and generator-specific in follow-on test |
| `0x02040898` | 0-1 | Shared/common AC voltage | `uint16` BE | x1 V | confirmed field; not generator-specific |
| `0x02040898` | 2-3 | Shared/common AC frequency | `uint16` BE | x1 Hz | confirmed field; can remain live on shore with generator off |
| `0x00501020` | 0-1 | Generator starter voltage | `uint16` LE | x0.1 V | strong installation correlation; published by bridge |
| six `0x060x0580` IDs | 0-1 | House battery voltage | `uint16` LE | x0.01 V | confirmed |
| six `0x060x0580` IDs | 4-5 | House battery SoC | `uint16` LE | x1 % | confirmed for this installation |

House-battery IDs:

```text
0x06020580  0x06060580  0x060A0580
0x060E0580  0x06120580  0x06160580
```

The physical 1-6 ordering is not yet proven.

## Generator lifecycle and Victron mapping

| Input | Physical interpretation | Bridge/Victron result |
|---|---|---|
| `02460B88#01` | START request | one CAN START; `STARTING`; Victron `/StatusCode=1` |
| `02440B88#02/#03` | startup status | remain `STARTING` |
| `005A1020` 47-53 Hz held 3 s | generator AC stable | `RUNNING`; `/StatusCode=8` |
| `02440B88#01` | settled running | `RUNNING_SETTLED`; `/StatusCode=8` |
| `02460B88#02` | STOP request | one CAN STOP; `STOPPING`; `/StatusCode=9` |
| `02440B88#05/#04` | shutdown status | remain `STOPPING` |
| `005A1020=0.0 Hz` | engine/frequency stopped | `STOPPED`; `/StatusCode=0` |
| `02440B88#00` | controller settled/ready | `OFF_IDLE`; `/StatusCode=0` |

`02440B88#06/#07` were observed as abort/error candidates but remain unresolved.

### Post-stop restart caveat

A live test showed that 0 Hz (`STOPPED`) can precede `02440B88#00` (`OFF_IDLE`) by roughly a minute. A START sent during that settling interval was ignored by the Scheiber controller; a later START from `OFF_IDLE` succeeded. Bridge v5.4.1 does not yet queue an early Victron START.

## Candidate / experimental mappings

| CAN ID | Bytes | Signal | Decode | Status |
|---|---|---|---|---|
| six house battery IDs | 2-3 | signed current | `(uint16LE - 0x4E00) * 0.1 A` | zero/sign strong; x0.1 A scale candidate |
| `0x06140580` | 0-1 | Engine Battery A voltage | `uint16LE * 0.00053 V` | experimental scale/identity |
| `0x06180580` | 0-1 | Engine Battery B voltage | `uint16LE * 0.00053 V` | experimental scale/identity |
| `0x00501008/1010/1020` | 0-1 | charger DC voltage | `uint16LE * 0.1 V` | candidate/high physical plausibility |
| `0x00501008/1010/1020` | 2-3 | charger DC current | `uint16LE * 0.1 A` | candidate |
| `0x00501008/1010/1020` | 4-5 | charger AC input voltage | `uint16LE * 0.1 V` | strong candidate |
| `0x00561008` byte 5 | n/a | rating signature | 60 A | candidate role |
| `0x00561010` byte 5 | n/a | rating signature | 40 A | candidate role |
| `0x00561020` byte 5 | n/a | rating signature | 25 A | candidate role / generator-start charging family |
| `0x00521008/1010` | 2-3 | temperature/counter-like value | `uint16LE` raw | unresolved |

## Source-control boundary

The bridge consumes applied source state and panel voltage only. It intentionally does **not** transmit:

```text
0x02420B90   AC-panel source request
0x02420B88   House-panel source request
0x02160B88   unresolved companion frame
0x02140B88   unresolved companion state
0x02440B88   generator feedback/state
```

The only production transmit ID in bridge v5.4.1 is `0x02460B88`, with one-byte START or STOP payloads. No automatic CAN retries are sent.

## Remaining unresolved work

- physical house-battery 1-6 ordering;
- engine A/B to port/starboard assignment and exact voltage scale;
- exact charger-to-bank wiring for 0x1008/0x1010;
- exact substage meaning of `02` vs `03`, and `05` vs `04`;
- `06`/`07` abort semantics;
- HVAC/air-conditioning IDs from a labelled follow-on capture;
- synthetic Victron `acsystem` modelling for Shore/Generator topology (not source control).
