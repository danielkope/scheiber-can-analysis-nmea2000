# Scheiber CAN Analysis — Engineering Report

This engineering report is split into review-friendly Markdown sections. The build script concatenates them in filename order to generate the complete PDF and DOCX report.

> **Evidence scope:** the generated report is intentionally anchored to the original hash-identified passive capture. Follow-on live control validation, the current Victron Cerbo GX production integration, and live Signal K/NMEA 2000 publication are documented separately in focused addenda. This keeps the historical evidence package reproducible while preventing newer field results from drifting out of the repository.

## Sections

- [Document control and evidence provenance](report/00_document_control_and_evidence_provenance.md)
- [1. Executive summary](report/01_1_executive_summary.md)
- [2. Scope, inventory, and limitations](report/02_2_scope_inventory_and_limitations.md)
- [3. Hardware, pinout, and bus checks](report/03_3_hardware_pinout_and_bus_checks.md)
- [4. Raspberry Pi capture procedure](report/04_4_raspberry_pi_capture_procedure.md)
- [5. Analysis method](report/05_5_analysis_method.md)
- [6. Confirmed tank mapping](report/06_6_confirmed_tank_mapping.md)
- [7. AC and House panel source switching](report/07_7_ac_and_house_panel_source_switching.md)
- [8. AC/generator telemetry and lifecycle state machine](report/08_8_ac_generator_telemetry.md)
- [9. Six house-battery candidates](report/09_9_six_house_battery_candidates.md)
- [10. Three charger families](report/10_10_three_charger_families.md)
- [11. Nine-battery assignment status](report/11_11_nine_battery_assignment_status.md)
- [12. Complete mapping register](report/14_00_mapping_12_complete_mapping_register.md)
- [Confirmed](report/14_01_mapping_confirmed.md)
- [Confirmed Field / Candidate Identity](report/14_02_mapping_confirmed_field_candidate_identity.md)
- [Candidate Role](report/14_03_mapping_candidate_role.md)
- [Candidate](report/14_04_mapping_candidate.md)
- [Guess](report/14_05_mapping_guess.md)
- [Unresolved](report/14_06_mapping_unresolved.md)
- [13. Proposed NMEA 2000 gateway](report/19_13_proposed_nmea_2000_gateway.md)
- [14. Reproduction and validation plan](report/20_14_reproduction_and_validation_plan.md)
- [Appendix A. Complete CAN-ID inventory](report/21_appendix_a_complete_can_id_inventory.md)
- [Appendix B. Selected raw evidence examples](report/22_appendix_b_selected_raw_evidence_examples.md)
- [Appendix C. References and external technical sources](report/23_appendix_c_references_and_external_technical_sources.md)

## Current live addenda

- [`AC_POWER_AND_INVERTERS.md`](AC_POWER_AND_INVERTERS.md): complete AC sources, 1 Hz heartbeat sample-and-hold telemetry, MasterVolt 2000W Inverter service, and GUI-v2 system topology.
- [`SWITCH_SERVICE_HANDOVER.md`](SWITCH_SERVICE_HANDOVER.md): native Victron switch service (`com.victronenergy.switch.scheiber`), Multibloc V8 sailing-panel mappings, and Node-RED automation flows (Anchor Light & Bilge Monitoring).
- [`GENERATOR_LIFECYCLE.md`](GENERATOR_LIFECYCLE.md): passive lifecycle model plus follow-on live START/STOP, OFF_IDLE, and Victron state-management findings.
- [`CERBO_GX_INTEGRATION.md`](CERBO_GX_INTEGRATION.md): tested bridge version, installation, D-Bus architecture, mappings, diagnostics, smart starter battery low-voltage alarms, and rollback.
- [`SIGNALK_NMEA2000.md`](SIGNALK_NMEA2000.md): live Signal K -> NMEA 2000 tank output, PGN 127505 instance mapping, VE.Can loopback verification, and B&G Zeus3 guidance.
- [`NMEA2000_MAPPING.md`](NMEA2000_MAPPING.md): current standard-PGN publication plan and live/deferred status.
- [`MAPPING_TABLE.md`](MAPPING_TABLE.md): current consolidated Scheiber CAN mapping register, including fields confirmed after the original report was generated.

## Build the baseline report

```bash
./scripts/build_report.sh
```

The build regenerates analysis outputs and figures from the hash-identified raw capture before producing the PDF and DOCX.
