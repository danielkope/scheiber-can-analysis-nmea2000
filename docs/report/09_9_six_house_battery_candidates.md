# 9. Six house-battery candidates

Exactly six similarly structured, six-byte message streams exist, matching the known six house batteries. Their first little-endian word decodes cleanly as centivolts. The IDs are assigned logical candidate numbers only; their physical battery positions are not implied by CAN-ID order.

| **Candidate** | **CAN ID** | **V min** | **V median** | **V max** | **Code min** | **Code median** | **Code max** | **Field 3** |
|---------------|------------|-----------|--------------|-----------|--------------|-----------------|--------------|-------------|
| 1             | 0x06020580 | 13.32     | 13.34        | 13.36     | -24          | 24              | 65           | 72          |
| 2             | 0x06060580 | 13.33     | 13.35        | 13.36     | -20          | 25              | 59           | 73          |
| 3             | 0x060A0580 | 13.33     | 13.34        | 13.35     | -3           | 24              | 48           | 72          |
| 4             | 0x060E0580 | 13.33     | 13.34        | 13.35     | -9           | 15              | 50           | 72          |
| 5             | 0x06120580 | 13.32     | 13.33        | 13.35     | -22          | 14              | 66           | 74          |
| 6             | 0x06160580 | 13.32     | 13.33        | 13.35     | -26          | 16              | 72           | 74          |

## 9.1 Byte layout

```text
Example: 06020580#35050A4E4800

bytes 0-1: 35 05 -> 0x0535 little-endian = 1333 -> 13.33 V
bytes 2-3: 0A 4E -> 0x4E0A little-endian - 0x4E00 = +10 current code
bytes 4-5: 48 00 -> 0x0048 little-endian = 72 field-3 units
```

| **Bytes** | **Datatype** | **Equation** | **Interpretation** | **Confidence** |
|---|---|---|---|---|
| 0-1 | uint16 LE | raw x 0.01 | Voltage in V | high |
| 2-3 | offset uint16 LE | raw - 0x4E00 | Signed current-like code | medium for sign |
| 2-3 derived | float guess | (raw - 0x4E00) x 0.1 | Current in A working guess | low-medium |
| 4-5 | uint16 LE | raw x 1 | SoC percent primary guess; degF alternative | low-medium |

> **Physical assignment remains open:** Do not label these IDs as physical Battery 1 through Battery 6 until one battery is loaded or isolated at a time. The current logical numbering is only a stable software instance order.
