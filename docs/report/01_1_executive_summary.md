# 1. Executive summary

The capture is internally consistent and fully parseable. Periodic heartbeat traffic identifies a controller family at suffix 0x0580, an AC/generator module at 0x0898, two panels at 0x0B88 and 0x0B90, an additional node at 0x0F80, and three multi-message devices at 0x1008, 0x1010, and 0x1020. The latter three are much more consistent with three chargers than with three individual batteries because each device emits heartbeat, DC/AC telemetry, configuration, rating signatures, and frequency messages.

| **Subsystem**        | **Finding**                                                                                   | **Status**                                     |
|----------------------|-----------------------------------------------------------------------------------------------|------------------------------------------------|
| Tanks                | Water 84% median = about 504 L; diesel 1 63% median = about 315 L; diesel 2 79% = about 395 L | confirmed/high                                 |
| AC panel selector    | Request 0x02420B90; applied 0x02400B90; 01 OFF, 02 SHORE, 04 GENERATOR                        | confirmed/high                                 |
| House panel selector | Request 0x02420B88; applied 0x02400B88; same enum                                             | confirmed/high                                 |
| Generator command    | 0x02460B88: 01 START, 02 STOP                                                                  | confirmed/high semantics; transmit disabled    |
| Break-before-make    | Transfers to generator include applied OFF before applied GENERATOR                           | confirmed/high                                 |
| AC voltage/frequency | 0x02040898: two big-endian uint16 values in V and Hz                                          | confirmed/high                                 |
| House batteries      | Six 0x060x0580 streams; voltage uint16LE x0.01 V                                              | field confirmed; physical assignment candidate |
| House current        | uint16LE minus 0x4E00 gives exact signed direction; x0.1 A is guessed                         | candidate                                      |
| House field 3        | 72-74; SoC percent is primary guess, degF temperature alternative                             | guess                                          |
| Chargers             | 0x1008, 0x1010, 0x1020 device families; likely 12 V / 60 A, 40 A, 25 A                        | candidate/medium-high                          |
| Starter batteries    | Port, starboard, generator-start physical CAN sources not isolated                            | unresolved                                     |

The START frame occurs at capture line 885 (+49.658548 s) and the STOP frame at line 3427 (+177.378315 s), matching the operator-reported sequence. Those semantics are confirmed, but safe transmission remains intentionally unimplemented because required companion frames, acknowledgement, timing, retries, interlocks, and fail-safe behavior are still unknown.
