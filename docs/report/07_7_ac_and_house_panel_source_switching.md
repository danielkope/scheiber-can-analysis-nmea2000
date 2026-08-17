# 7. AC and House panel source switching

## 7.1 Confirmed enum and message roles

| **Raw** | **Meaning** |
|---------|-------------|
| 0x01    | OFF         |
| 0x02    | SHORE       |
| 0x04    | GENERATOR   |

| **Panel** | **Request ID** | **Applied/accepted ID** |
|-----------|----------------|-------------------------|
| AC        | 0x02420B90     | 0x02400B90              |
| House     | 0x02420B88     | 0x02400B88              |

Request frames occur at the user interface; applied frames arrive later after the controller accepts or completes the transition. This distinction is important for a gateway: a request is not proof that the contactor state changed.

## 7.2 Clean decoded operation sequence

| **Step** | **t (s)** | **Line** | **Panel**   | **Frame role** | **Raw** | **Decoded** | **Raw frame** |
|----------|-----------|----------|-------------|----------------|---------|-------------|---------------|
| 1        | 66.076    | 1276     | AC panel    | request        | 0x01    | OFF         | 02420B90#01   |
| 2        | 67.591    | 1311     | AC panel    | applied        | 0x01    | OFF         | 02400B90#01   |
| 3        | 106.121   | 2028     | AC panel    | request        | 0x02    | SHORE       | 02420B90#02   |
| 4        | 107.488   | 2055     | AC panel    | applied        | 0x02    | SHORE       | 02400B90#02   |
| 5        | 121.217   | 2318     | AC panel    | request        | 0x04    | GENERATOR   | 02420B90#04   |
| 6        | 122.773   | 2353     | AC panel    | applied        | 0x01    | OFF         | 02400B90#01   |
| 7        | 123.375   | 2365     | AC panel    | applied        | 0x04    | GENERATOR   | 02400B90#04   |
| 8        | 142.947   | 2702     | House panel | request        | 0x01    | OFF         | 02420B88#01   |
| 9        | 144.488   | 2731     | House panel | applied        | 0x01    | OFF         | 02400B88#01   |
| 10       | 155.523   | 2965     | House panel | request        | 0x02    | SHORE       | 02420B88#02   |
| 11       | 156.877   | 2992     | House panel | applied        | 0x02    | SHORE       | 02400B88#02   |
| 12       | 163.989   | 3147     | House panel | request        | 0x04    | GENERATOR   | 02420B88#04   |
| 13       | 165.549   | 3181     | House panel | applied        | 0x01    | OFF         | 02400B88#01   |
| 14       | 166.121   | 3195     | House panel | applied        | 0x04    | GENERATOR   | 02400B88#04   |

<table>
<colgroup>
<col style="width: 100%" />
</colgroup>
<thead>
<tr class="header">
<th><strong>Break-before-make evidence</strong><br />
For both panels, the Shore-to-Generator transition includes an applied OFF state before applied GENERATOR. A future bridge must never collapse this sequence into a direct make-before-break transfer.</th>
</tr>
</thead>
<tbody>
</tbody>
</table>

Earlier repeated request-only frames occur before the clean applied sequence. They may be button repeats, UI previews, retries, or requests rejected by interlocks. The mapping therefore treats request and applied IDs separately.

