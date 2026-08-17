# Document control and evidence provenance

| **Item**              | **Value**                                                                         |
|-----------------------|-----------------------------------------------------------------------------------|
| Source file           | d5175281-0a41-493a-ae0d-fb84baba6d2f.log                                          |
| Source path in bundle | data/raw/d5175281-0a41-493a-ae0d-fb84baba6d2f.log.xz                              |
| SHA-256               | 47296d01c77acc01bc32621e8b0bbdb7c6f7e4837da1c207342baba30a281641                  |
| File size             | 207,809 bytes uncompressed                                                        |
| Frame count           | 4,401                                                                             |
| Unique CAN IDs        | 45                                                                                |
| Interface             | can1                                                                              |
| Parse errors          | 0                                                                                 |
| Capture start UTC     | 2026-08-17T15:13:45.028287+00:00                                                  |
| Capture end UTC       | 2026-08-17T15:17:33.990442+00:00                                                  |
| Duration              | 228.962155 seconds                                                                |
| Local time basis      | Europe/Vienna, CEST (UTC+02:00) for this date                                     |
| Identifier form       | 29-bit extended IDs inferred from 8-hex-digit identifiers                         |
| Analyzer              | scripts/scheiber_can_analyze.py; standard-library parser and conservative decoder |
| Build environment     | Python 3.13.5 on Linux 6.18.35                                                    |

## Abstract

A 228.962-second Scheiber CAN capture was analyzed to recover tank levels, two source-selection panel state machines, confirmed direct generator START/STOP commands, AC voltage/frequency telemetry, six individual house-battery candidate streams, and three multi-message charger families. The report separates direct evidence from engineering inference. The strongest charger interpretation is a set of 12 V devices with 60 A, 40 A, and 25 A rating signatures; the 25 A family is the best generator-start charger candidate, but physical wiring remains unconfirmed. The report includes the complete mapping register, raw evidence examples, Raspberry Pi and SH-C30A setup, and a safe two-interface architecture for translating selected signals to NMEA 2000.

<table>
<colgroup>
<col style="width: 100%" />
</colgroup>
<thead>
<tr class="header">
<th><strong>Confidence vocabulary</strong><br />
Confirmed means directly correlated or physically unambiguous. Candidate means a strong engineering inference that needs a controlled validation. Guess is a useful working hypothesis. Unresolved means the field is preserved without invented semantics.</th>
</tr>
</thead>
<tbody>
</tbody>
</table>

## Contents

- 1. Executive summary
- 2. Scope, inventory, and limitations
- 3. Hardware, pinout, and bus checks
- 4. Raspberry Pi capture procedure
- 5. Analysis method
- 6. Confirmed tank mapping
- 7. AC and House panel source switching
- 8. AC/generator telemetry and commands
- 9. Six house-battery candidates
- 10. Three charger families
- 11. Nine-battery assignment status
- 12. Complete mapping register
- 13. NMEA 2000 gateway proposal
- 14. Reproduction and validation plan
- Appendix A. CAN-ID inventory
- Appendix B. Raw evidence examples
- Appendix C. References
