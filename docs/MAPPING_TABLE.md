# Scheiber CAN mapping register

> Status labels are intentional: confirmed, candidate, guess, and unresolved are not interchangeable.
> Generator command semantics are confirmed; command transmission remains disabled until safety behavior is validated.

Total mapping rows: **89**. The separate `can_id_inventory.csv` lists every observed CAN ID and frame count.

## Confirmed and high-confidence fields

| CAN ID | Bytes | Signal | Type / endian | Scale / unit | Status | Confidence |
|---|---|---|---|---|---|---|
| `0x02040580` | 0-1 | Water tank level | uint16 / big | x 1 % | confirmed | high |
| `0x02040580` | 2-3 | Diesel tank 1 level | uint16 / big | x 1 % | confirmed | high |
| `0x02040580` | 4-5 | Diesel tank 2 level | uint16 / big | x 1 % | confirmed | high |
| `0x02420B90` | 0 | AC panel requested source | uint8 enum / n/a | 1=OFF, 2=SHORE, 4=GENERATOR enum | confirmed | high |
| `0x02400B90` | 0 | AC panel applied source | uint8 enum / n/a | 1=OFF, 2=SHORE, 4=GENERATOR enum | confirmed | high |
| `0x02420B88` | 0 | House panel requested source | uint8 enum / n/a | 1=OFF, 2=SHORE, 4=GENERATOR enum | confirmed | high |
| `0x02400B88` | 0 | House panel applied source | uint8 enum / n/a | 1=OFF, 2=SHORE, 4=GENERATOR enum | confirmed | high |
| `0x02460B88` | 0 | Generator direct command | uint8 enum / n/a | 1=START, 2=STOP enum | confirmed semantics; transmit disabled | high |
| `0x02040B90` | 0-3 | AC panel leading reserved words | 2 x uint16 / big | none raw | confirmed | high |
| `0x02040B90` | 4-5 | AC panel AC voltage | uint16 / big | x 1 V | confirmed | high |
| `0x02040B88` | 0-3 | House panel leading reserved words | 2 x uint16 / big | none raw | confirmed | high |
| `0x02040B88` | 4-5 | House panel AC voltage | uint16 / big | x 1 V | confirmed | high |
| `0x02060B88` | 2-3 | House DC unavailable/reserved | uint16 / big | none raw | confirmed | high |
| `0x02040898` | 0-1 | Generator/AC module voltage | uint16 / big | x 1 V | confirmed | high |
| `0x02040898` | 2-3 | Generator/AC module frequency | uint16 / big | x 1 Hz | confirmed | high |
| `0x06020580` | 0-1 | House battery candidate 1 voltage | uint16 / little | x 0.01 V | confirmed field / candidate identity | high / medium |
| `0x06060580` | 0-1 | House battery candidate 2 voltage | uint16 / little | x 0.01 V | confirmed field / candidate identity | high / medium |
| `0x060A0580` | 0-1 | House battery candidate 3 voltage | uint16 / little | x 0.01 V | confirmed field / candidate identity | high / medium |
| `0x060E0580` | 0-1 | House battery candidate 4 voltage | uint16 / little | x 0.01 V | confirmed field / candidate identity | high / medium |
| `0x06120580` | 0-1 | House battery candidate 5 voltage | uint16 / little | x 0.01 V | confirmed field / candidate identity | high / medium |
| `0x06160580` | 0-1 | House battery candidate 6 voltage | uint16 / little | x 0.01 V | confirmed field / candidate identity | high / medium |
| `0x00501008` | 6-7 | Charger 1008 unavailable/reserved | uint16 / little | none raw | confirmed | high |
| `0x005A1008` | 2-7 | Charger 1008 unavailable/reserved | 3 x uint16 / little | none raw | confirmed | high |
| `0x00501010` | 6-7 | Charger 1010 unavailable/reserved | uint16 / little | none raw | confirmed | high |
| `0x005A1010` | 2-7 | Charger 1010 unavailable/reserved | 3 x uint16 / little | none raw | confirmed | high |
| `0x00501020` | 6-7 | Charger 1020 unavailable/reserved | uint16 / little | none raw | confirmed | high |
| `0x005A1020` | 2-7 | Charger 1020 unavailable/reserved | 3 x uint16 / little | none raw | confirmed | high |
| `0x00000580` | 0-4 | 0x0580 controller heartbeat | fixed byte array / n/a | none raw | candidate role | medium-high |
| `0x00000898` | 0-4 | 0x0898 AC/generator module heartbeat | fixed byte array / n/a | none raw | candidate role | medium-high |
| `0x00000B88` | 0-4 | House panel heartbeat | fixed byte array / n/a | none raw | candidate role | medium-high |
| `0x00000B90` | 0-4 | AC panel heartbeat | fixed byte array / n/a | none raw | candidate role | medium-high |
| `0x00000F80` | 0-4 | Unknown node heartbeat | fixed byte array / n/a | none raw | candidate role | medium-high |
| `0x00001008` | 0-4 | Charger 1008 heartbeat | fixed byte array / n/a | none raw | candidate role | medium-high |
| `0x00001010` | 0-4 | Charger 1010 heartbeat | fixed byte array / n/a | none raw | candidate role | medium-high |
| `0x00001020` | 0-4 | Charger 1020 heartbeat | fixed byte array / n/a | none raw | candidate role | medium-high |

## Candidate and guessed fields

| CAN ID | Bytes | Signal | Type / endian | Scale / unit | Status | Confidence |
|---|---|---|---|---|---|---|
| `0x02060580` | 4-5 | Central DC voltage candidate | uint16 / big | x 0.1 candidate V | candidate | medium |
| `0x02040B90` | 6-7 | AC panel frequency/status word | uint16 / big | usually x 1 Hz-like/raw | candidate | medium |
| `0x02040B88` | 6-7 | House panel frequency/status word | uint16 / big | usually x 1 Hz-like/raw | candidate | medium |
| `0x02060B88` | 0-1 | House DC voltage candidate | uint16 / big | x 0.1 V | candidate | medium-high |
| `0x02140898` | 0 | Generator/AC transition marker | uint8 enum / n/a | 02=ramp-down, 03=ramp-up (observed) enum candidate | candidate | medium |
| `0x06020580` | 2-3 | House battery candidate 1 signed current code | offset uint16 / little | raw - 0x4E00; x 0.1 A guessed A candidate | candidate | medium for sign; low-medium for A scale |
| `0x06020580` | 4-5 | House battery candidate 1 field 3 | uint16 / little | x 1 candidate % SoC guess or degF alternative | guess | low-medium |
| `0x06060580` | 2-3 | House battery candidate 2 signed current code | offset uint16 / little | raw - 0x4E00; x 0.1 A guessed A candidate | candidate | medium for sign; low-medium for A scale |
| `0x06060580` | 4-5 | House battery candidate 2 field 3 | uint16 / little | x 1 candidate % SoC guess or degF alternative | guess | low-medium |
| `0x060A0580` | 2-3 | House battery candidate 3 signed current code | offset uint16 / little | raw - 0x4E00; x 0.1 A guessed A candidate | candidate | medium for sign; low-medium for A scale |
| `0x060A0580` | 4-5 | House battery candidate 3 field 3 | uint16 / little | x 1 candidate % SoC guess or degF alternative | guess | low-medium |
| `0x060E0580` | 2-3 | House battery candidate 4 signed current code | offset uint16 / little | raw - 0x4E00; x 0.1 A guessed A candidate | candidate | medium for sign; low-medium for A scale |
| `0x060E0580` | 4-5 | House battery candidate 4 field 3 | uint16 / little | x 1 candidate % SoC guess or degF alternative | guess | low-medium |
| `0x06120580` | 2-3 | House battery candidate 5 signed current code | offset uint16 / little | raw - 0x4E00; x 0.1 A guessed A candidate | candidate | medium for sign; low-medium for A scale |
| `0x06120580` | 4-5 | House battery candidate 5 field 3 | uint16 / little | x 1 candidate % SoC guess or degF alternative | guess | low-medium |
| `0x06160580` | 2-3 | House battery candidate 6 signed current code | offset uint16 / little | raw - 0x4E00; x 0.1 A guessed A candidate | candidate | medium for sign; low-medium for A scale |
| `0x06160580` | 4-5 | House battery candidate 6 field 3 | uint16 / little | x 1 candidate % SoC guess or degF alternative | guess | low-medium |
| `0x00501008` | 0-1 | Charger 1008 DC output voltage candidate | uint16 / little | x 0.1 V | candidate | medium-high |
| `0x00501008` | 2-3 | Charger 1008 DC output current candidate | uint16 / little | x 0.1 A | candidate | medium |
| `0x00501008` | 4-5 | Charger 1008 AC input voltage candidate | uint16 / little | x 0.1 V | candidate | high |
| `0x00561008` | 0-1 | Charger 1008 dynamic channel A | uint16 / little | x 0.1 candidate V/A candidate | candidate | low-medium |
| `0x00561008` | 2-3 | Charger 1008 dynamic channel B | uint16 / little | x 0.1 candidate V/A candidate | candidate | low-medium |
| `0x00561008` | 4 | Charger 1008 nominal voltage signature | uint8 / n/a | x 1 V candidate | candidate | medium-high |
| `0x00561008` | 5 | Charger 1008 rated current signature | uint8 / n/a | x 1 A candidate | candidate | medium-high |
| `0x005A1008` | 0-1 | Charger 1008 AC frequency | uint16 / little | x 0.1 Hz | candidate | high |
| `0x00501010` | 0-1 | Charger 1010 DC output voltage candidate | uint16 / little | x 0.1 V | candidate | medium-high |
| `0x00501010` | 2-3 | Charger 1010 DC output current candidate | uint16 / little | x 0.1 A | candidate | medium |
| `0x00501010` | 4-5 | Charger 1010 AC input voltage candidate | uint16 / little | x 0.1 V | candidate | high |
| `0x00561010` | 0-1 | Charger 1010 dynamic channel A | uint16 / little | x 0.1 candidate V/A candidate | candidate | low-medium |
| `0x00561010` | 2-3 | Charger 1010 dynamic channel B | uint16 / little | x 0.1 candidate V/A candidate | candidate | low-medium |
| `0x00561010` | 4 | Charger 1010 nominal voltage signature | uint8 / n/a | x 1 V candidate | candidate | medium-high |
| `0x00561010` | 5 | Charger 1010 rated current signature | uint8 / n/a | x 1 A candidate | candidate | medium-high |
| `0x005A1010` | 0-1 | Charger 1010 AC frequency | uint16 / little | x 0.1 Hz | candidate | high |
| `0x00501020` | 0-1 | Charger 1020 DC output voltage candidate | uint16 / little | x 0.1 V | candidate | medium-high |
| `0x00501020` | 2-3 | Charger 1020 DC output current candidate | uint16 / little | x 0.1 A | candidate | medium |
| `0x00501020` | 4-5 | Charger 1020 AC input voltage candidate | uint16 / little | x 0.1 V | candidate | high |
| `0x00561020` | 0-1 | Charger 1020 dynamic channel A | uint16 / little | x 0.1 candidate V/A candidate | candidate | low-medium |
| `0x00561020` | 2-3 | Charger 1020 dynamic channel B | uint16 / little | x 0.1 candidate V/A candidate | candidate | low-medium |
| `0x00561020` | 4 | Charger 1020 nominal voltage signature | uint8 / n/a | x 1 V candidate | candidate | medium-high |
| `0x00561020` | 5 | Charger 1020 rated current signature | uint8 / n/a | x 1 A candidate | candidate | medium-high |
| `0x005A1020` | 0-1 | Charger 1020 AC frequency | uint16 / little | x 0.1 Hz | candidate | high |

## Unresolved fields

| CAN ID | Bytes | Signal | Type / endian | Scale / unit | Status | Confidence |
|---|---|---|---|---|---|---|
| `0x02040580` | 6-7 | Tank frame state / quality / sequence | uint16 / big | unknown raw | unresolved | low |
| `0x02060580` | 0-1 | Central sensor value A | uint16 / big | unknown raw | unresolved | low |
| `0x02060580` | 2-3 | Central sensor flags/counter | uint16 / big | unknown raw | unresolved | low |
| `0x00561008` | 6-7 | Charger 1008 config/status bytes | 2 x uint8 / n/a | unknown raw | unresolved | low |
| `0x00561010` | 6-7 | Charger 1010 config/status bytes | 2 x uint8 / n/a | unknown raw | unresolved | low |
| `0x00561020` | 6-7 | Charger 1020 config/status bytes | 2 x uint8 / n/a | unknown raw | unresolved | low |
| `0x00521008 / 0x00521010` | 2-3 | Charger temperature/counter candidate | uint16 / little | unknown raw or K candidate | unresolved | low |
| `0x00541008 / 0x00541010 / 0x00541020` | 0-7 | Charger sparse configuration/status | byte array / mixed/unknown | unknown raw | unresolved | low |
| `0x02140B88` | all | House-panel mode/state | byte array / unknown | unknown raw | unresolved | low |
| `0x02140B90` | all | AC-panel mode/state | byte array / unknown | unknown raw | unresolved | low |
| `0x02160B88` | all | House-panel bitfield/state | byte array / unknown | unknown raw | unresolved | low |
| `0x02440B88` | all | House-panel transition/config | byte array / unknown | unknown raw | unresolved | low |
| `0x00080000` | all | Global/time/status frame | byte array / unknown | unknown raw | unresolved | low |
