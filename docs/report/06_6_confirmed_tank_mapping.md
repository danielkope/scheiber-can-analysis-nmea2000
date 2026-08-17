# 6. Confirmed tank mapping

CAN ID 0x02040580 is an eight-byte frame containing four big-endian unsigned 16-bit values. The first three match the user-recorded tank levels exactly. The fourth word varies only between 0, 1, and 2 and remains unresolved.

<table>
<colgroup>
<col style="width: 100%" />
</colgroup>
<thead>
<tr class="header">
<th>02040580#0054003F004F0001<br />
0054 003F 004F 0001<br />
84 63 79 1 (uint16 big-endian)</th>
</tr>
</thead>
<tbody>
</tbody>
</table>

| **Bytes** | **Datatype** | **Scale** | **Decoded signal**               | **Observed**       | **Capacity** | **Derived volume** | **Confidence** |
|-----------|--------------|-----------|----------------------------------|--------------------|--------------|--------------------|----------------|
| 0-1       | uint16 BE    | 1 %/count | Water level                      | 83-85%, median 84% | 600 L        | 504 L at 84%       | high           |
| 2-3       | uint16 BE    | 1 %/count | Diesel 1 level                   | 63-64%, median 63% | 500 L        | 315 L at 63%       | high           |
| 4-5       | uint16 BE    | 1 %/count | Diesel 2 level                   | 79%                | 500 L        | 395 L              | high           |
| 6-7       | uint16 BE    | unknown   | State/quality/sequence candidate | 0,1,2              | n/a          | n/a                | low            |

<img src="figures/tank_levels.png" style="width:6.4in;height:3.45935in" />

*Figure 3. Median tank levels and derived litres.*

For NMEA 2000 translation, use PGN 127505 with water instance 0 and fuel instances 1 and 2. Preserve capacity as 600 L, 500 L, and 500 L. The fourth Scheiber word should not be forwarded until its meaning is known.

