# Scheiber CAN Analysis — Engineering Report

This engineering report is split into review-friendly Markdown sections. The build script concatenates them in filename order to generate the complete PDF and DOCX report.

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

A focused, implementation-oriented version of the generator state machine is also available at [`GENERATOR_LIFECYCLE.md`](GENERATOR_LIFECYCLE.md).

## Build the complete report

```bash
./scripts/build_report.sh
```

The build regenerates analysis outputs and figures from the hash-identified raw capture before producing the PDF and DOCX.
