# 12.5 Mapping register — Guess

| **CAN ID** | **Bytes** | **Signal**                        | **Type / endian** | **Scale / unit**                              | **Confidence** | **Interpretation**                                 |
|------------|-----------|-----------------------------------|-------------------|-----------------------------------------------|----------------|----------------------------------------------------|
| 0x06020580 | 4-5       | House battery candidate 1 field 3 | uint16 / little   | x 1 candidate % SoC guess or degF alternative | low-medium     | SoC is primary guess; temperature remains credible |
| 0x06060580 | 4-5       | House battery candidate 2 field 3 | uint16 / little   | x 1 candidate % SoC guess or degF alternative | low-medium     | SoC is primary guess; temperature remains credible |
| 0x060A0580 | 4-5       | House battery candidate 3 field 3 | uint16 / little   | x 1 candidate % SoC guess or degF alternative | low-medium     | SoC is primary guess; temperature remains credible |
| 0x060E0580 | 4-5       | House battery candidate 4 field 3 | uint16 / little   | x 1 candidate % SoC guess or degF alternative | low-medium     | SoC is primary guess; temperature remains credible |
| 0x06120580 | 4-5       | House battery candidate 5 field 3 | uint16 / little   | x 1 candidate % SoC guess or degF alternative | low-medium     | SoC is primary guess; temperature remains credible |
| 0x06160580 | 4-5       | House battery candidate 6 field 3 | uint16 / little   | x 1 candidate % SoC guess or degF alternative | low-medium     | SoC is primary guess; temperature remains credible |

