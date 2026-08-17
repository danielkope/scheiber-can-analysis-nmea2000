# 5. Analysis method

The included analyzer parses each candump line, inventories IDs and periods, separates stable from changing bytes, tests big- and little-endian word interpretations, correlates changes with the operator action order, and evaluates physically plausible scales. Derived values are retained in long-form CSV with datatype, endian, scale, offset, unit, confidence, status, and notes.

9.  Parse and validate every line; reject malformed data rather than silently skipping it.

10. Group by 29-bit CAN ID and payload length; count unique payloads and transmission periods.

11. Identify heartbeats as fixed payloads recurring at approximately one second.

12. Locate event-driven IDs around labelled source-selection actions.

13. Test integer word boundaries and both endian orders.

14. Use known tank percentages and AC quantities to establish exact scales.

15. Use repeated six-node symmetry to identify house-battery candidates.

16. Use repeated multi-message suffixes and constant rating bytes to identify chargers.

17. Mark contradictory or unvalidated interpretations as candidate, guess, or unresolved.

<img src="figures/can_id_counts.png" style="width:6.7in;height:4.44316in" />

*Figure 2. The twenty most frequent CAN IDs. Periodic controller, panel, and charger heartbeats dominate the capture.*

## 5.1 Reproduction command

<table>
<colgroup>
<col style="width: 100%" />
</colgroup>
<thead>
<tr class="header">
<th>python3 scripts/scheiber_can_analyze.py \<br />
data/raw/d5175281-0a41-493a-ae0d-fb84baba6d2f.log \<br />
--config config/system_config.json \<br />
--output analysis-output</th>
</tr>
</thead>
<tbody>
</tbody>
</table>

