# Scheiber V8 control-panel raw captures

These files are the evidence used for the control-panel mapping in
[`docs/control-panel-v8/`](../../../docs/control-panel-v8/).

They are stored unchanged from the uploaded `candump -L` captures.

| File | Frames | Duration | SHA-256 |
|---|---:|---:|---|
| `panel-switch-sequence-2026-08-18.log` | 320 | 88.507635 s | `bf035f80627716379f7ea0618ae4f657cd6d82ab84c750f1492176c55c9793f7` |
| `water-pump-demand-2026-08-18.log` | 40 | 22.354069 s | `43feb9b8008e7348a8ca32af723802b2396fac0aee9cbfae46ce5f8664feb875` |

## Operator sequence for the first capture

The operator reported performing these actions, in this order:

1. Fridge ON, OFF.
2. Fresh-water pump ON, OFF.
3. Starboard bilge: AUTO ON, MANUAL ON/pumping, OFF.
4. Port bilge: AUTO ON, MANUAL ON/pumping, OFF.
5. Cabin lighting ON, OFF.
6. Anchor light ON, OFF.
7. Deck floodlight ON, OFF.
8. Steaming light ON; navigation lights were automatically turned ON and remained ON; steaming light OFF.
9. Navigation lights, already ON: OFF, ON, OFF.
10. Navigation electronics/chart plotter ON, OFF.

The second capture began with the fresh-water-pump enable already ON. A tap was
opened so that the pressure-water pump had to run, then closed.

Do not reorder or “clean up” these files: their exact timestamps and frame
ordering are part of the evidence.
