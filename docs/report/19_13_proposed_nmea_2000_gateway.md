# 13. Proposed NMEA 2000 gateway

## 13.1 Architecture

<table>
<colgroup>
<col style="width: 100%" />
</colgroup>
<thead>
<tr class="header">
<th>Scheiber proprietary CAN<br />
|<br />
v<br />
Isolated CAN interface A &lt;--- receive-only<br />
|<br />
Raspberry Pi translation service<br />
|<br />
Isolated CAN interface B ---&gt; NMEA 2000 / VE.Can<br />
|<br />
v<br />
Cerbo GX / navigation displays</th>
</tr>
</thead>
<tbody>
</tbody>
</table>

Scheiber and NMEA 2000 are not directly protocol-compatible. A gateway must decode Scheiber frames, apply instance and unit mappings, then construct valid NMEA 2000 PGNs on a separate CAN segment. It must never forward the original 29-bit identifier unchanged.

## 13.2 PGN plan

| **Scheiber data**                    | **Proposed PGN**                   | **Instance plan**                           | **Readiness**                              |
|--------------------------------------|------------------------------------|---------------------------------------------|--------------------------------------------|
| Water / diesel levels and capacities | 127505 Fluid Level                 | water 0; fuel 1 and 2                       | ready                                      |
| Six house battery voltages           | 127508 Battery Status              | battery 0-5                                 | voltage ready                              |
| Port/starboard/generator batteries   | 127508 Battery Status              | battery 6-8                                 | source IDs unresolved                      |
| SoC / remaining capacity             | 127506 DC Detailed Status          | same battery instances                      | await field-3 proof                        |
| Charger operating/configuration      | 127507 / 127510                    | charger 0-2                                 | families identified; state bits incomplete |
| AC input/output quantities           | 127503 / 127504; optionally 127747 | panel/source instances                      | voltage/frequency mostly ready             |
| Panel source states                  | 127501 Binary Switch Bank Status   | three mutually exclusive channels per panel | status possible                            |
| Panel control                        | 127502 Switch Bank Control         | same channels                               | disabled by default                        |
| Generator state                      | 127514 AGS Status or binary status | generator 0                                 | direct command semantics confirmed; transmit disabled |

## 13.3 Safety defaults

- Scheiber interface receive-only.

- NMEA 2000 output initially disabled; use scripts/nmea2000_dry_run.py to inspect JSON records.

- Publish tanks and confirmed voltage/frequency before any candidate battery current or SoC fields.

- Do not publish false precision: omit current, temperature, and SoC until calibrated.

- Do not implement source-selector or generator control until acknowledgements, interlocks, timeout behavior, companion frames, and fail-safe OFF/STOP behavior are proven.

## 13.4 Dry-run example

<table>
<colgroup>
<col style="width: 100%" />
</colgroup>
<thead>
<tr class="header">
<th>python3 scripts/nmea2000_dry_run.py data/raw/d5175281-0a41-493a-ae0d-fb84baba6d2f.log \<br />
--config config/system_config.json \<br />
--output nmea2000-dry-run.jsonl</th>
</tr>
</thead>
<tbody>
</tbody>
</table>

