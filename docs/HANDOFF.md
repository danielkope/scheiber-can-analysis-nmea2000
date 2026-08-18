# Future-engineer handoff

## Evidence baseline

The original passive evidence package remains unchanged:

- raw capture: `data/raw/d5175281-0a41-493a-ae0d-fb84baba6d2f.log.xz`
- uncompressed SHA-256: `47296d01c77acc01bc32621e8b0bbdb7c6f7e4837da1c207342baba30a281641`
- frames: 4,401
- unique extended CAN IDs: 45
- duration: 228.962155 s
- UTC interval: 2026-08-17 15:13:45.028287 to 15:17:33.990442

The baseline reconstructs START through RUNNING_SETTLED and STOP through 0 Hz / STOPPED. It does not contain `02440B88#00`; that state was confirmed later.

## Current Cerbo production integration

Tested environment:

```text
Cerbo GX / Venus OS v3.75
kernel 6.12.90-venus-2, armv7l
DSD TECH SH-C30A / gs_usb
Scheiber CAN can2 @ 250000 bit/s
service /service/scheiber-gx
persistent app /data/scheiber-gx
```

Bridge:

```text
version 5.4.2
canonical source cerbo/bridge.py
D-Bus service com.victronenergy.genset.scheiber
Victron manager com.victronenergy.generator.startstop1
SHA-256 6c25ce4b095385217564fc6bf6fdc843dfefd835993d643843811e7f0f737097
field-tested v5.4.1 source SHA-256 b7acb294467147a50166ac1468fe64de37c8a0facca920f3d0e8f2f89ee5a5c1
```

Version 5.4.2 keeps the field-tested v5.4.1 generator/CAN behavior and fixes the tank D-Bus volume unit. The repository now stores the complete production Python source directly; there is no encoded source, assembler, or install-time source patching.

Installation and debugging are in `docs/CERBO_GX_INTEGRATION.md`; the installer is `cerbo/install.sh`. Fresh installation and update both use that same direct-from-repository installer.

## Proven generator control

```text
02460B88#01 = START
02460B88#02 = STOP
```

Both commands were live-tested. Production behavior is one CAN transmission per accepted Victron transition, with no automatic retries.

Feedback:

```text
02440B88#01       RUNNING_SETTLED
02440B88#00       OFF_IDLE
02440B88#02/#03   STARTING
02440B88#04/#05   STOPPING
005A1020 LE16*0.1 generator-specific Hz
```

Live tests also established that `02040898` can show shore/common 235 V / 50 Hz while generator-specific `005A1020` remains 0 Hz with the generator off.

## Victron behavior validated

- connected-genset `/Start` is manager-owned command state;
- physical feedback updates `/StatusCode`, never `/Start`;
- external Scheiber START can be adopted through manager `/ManualStart=1` without duplicate CAN TX;
- native timed runs count down `/ManualStartTimer`, count up `/Runtime`, and stop with one CAN STOP at expiry;
- manager restart recovery suppresses the replacement manager's initialization STOP and restores manual/timed ownership;
- the old gui-v2 live +/- timer controls are no longer present in current UI source; do not add fake D-Bus flags to the bridge to chase that UI behavior.

## Important current limitation

After STOP, 0 Hz / `STOPPED` occurs before `02440B88#00` / `OFF_IDLE`. The settling delay was around one minute in a live test. A START sent during that window was ignored by Scheiber; a START from `OFF_IDLE` succeeded.

A future bridge version may queue a Victron `/Start=1` received while recently `STOPPED`, send exactly one physical START upon `#00`, and cancel the queued action if Victron returns `/Start=0` first. Do not implement retries and do not alter `/ManualStartTimer` semantics.

## Current telemetry

### Tanks

`02040580` BE words: fresh %, diesel1 %, diesel2 %. Vessel capacities: 600 L, 500 L, 500 L.

Published native Victron tank services use the Victron D-Bus volume unit:

```text
/Level      percent
/Capacity   cubic metres
/Remaining  cubic metres
```

Therefore the configured capacities are published as `0.600`, `0.500`, and `0.500 m3`. The service text formatter presents those values as litres for the GX UI. This unit correction is the runtime change from bridge v5.4.1 to v5.4.2.

### Signal K / NMEA 2000 tanks

The tank path is now live, not merely proposed.

Venus-derived Signal K sources:

```text
tanks.freshWater.90
tanks.fuel.91
tanks.fuel.92
```

Current `signalk-to-nmea2000` mappings:

```text
tanks.freshWater.90 -> PGN 127505 instance 6 Water
tanks.fuel.91       -> PGN 127505 instance 7 Fuel
tanks.fuel.92       -> PGN 127505 instance 8 Fuel
```

Observed loopback from the Cerbo VE.Can/NMEA 2000 connection:

```text
tanks.freshWater.6  source n2k-on-ve.can-socket.209 (127505)
tanks.fuel.7        source n2k-on-ve.can-socket.210 (127505)
tanks.fuel.8        source n2k-on-ve.can-socket.211 (127505)
```

The looped-back values matched the Venus values. The `209/210/211` values are NMEA source addresses, not tank instances, and should not be treated as stable configuration identifiers.

B&G Zeus3 published specifications include PGN 127505 as a receive PGN, so the standard on-bus representation is compatible with the plotter. See `docs/SIGNALK_NMEA2000.md` for display/source setup guidance and troubleshooting.

### House batteries

Six IDs:

```text
06020580 06060580 060A0580 060E0580 06120580 06160580
```

- bytes 0-1 LE x0.01 V: confirmed;
- bytes 2-3 `(raw-0x4E00)*0.1 A`: sign/offset strong, scale candidate;
- bytes 4-5 LE x1 %: SoC confirmed for this installation.

Keep the existing SmartShunt explicitly selected as the GX system battery. The bridge intentionally refuses to register extra battery services while the selection is `default`.

### Engine batteries

`06140580` and `06180580` are experimental A/B channels. Current voltage scale 0.00053 V/count is plausible but still requires one-engine-at-a-time crank validation and port/starboard assignment.

### Generator starter

`00501020` bytes 0-1 LE x0.1 V is published as starter voltage. Charger current and AC input are diagnostic/candidate fields.

This is the recommended next NMEA 2000 battery value, using PGN 127508 with a deliberate unused battery instance.

### Source panels

Applied source: `02400B90` AC and `02400B88` House; enum `01 OFF / 02 SHORE / 04 GENERATOR`. Panel voltage is bytes 4-5 BE of `02040B90` / `02040B88`.

Request IDs `02420B90` / `02420B88` are documented but not transmitted by the bridge.

## Deferred work

1. Post-stop queued START until `OFF_IDLE`.
2. Optional synthetic `com.victronenergy.acsystem.scheiber` for correct Shore/Generator topology/UI on systems with no VE.Bus/acsystem. Keep source selection receive-only and do not expose unsupported control paths.
3. Labelled HVAC/air-conditioning CAN capture now that the units can be operated one at a time.
4. Engine A/B physical identity and scale validation.
5. Physical house-battery 1-6 ordering.
6. Additional NMEA 2000 telemetry, starting with generator-starter voltage. Do not publish candidate house current or experimental engine-battery data as authoritative values.

## Service/debug commands

```bash
svc -d /service/scheiber-gx
svc -u /service/scheiber-gx

tail -n 100 /data/scheiber-gx/bridge.log
cat /data/scheiber-gx/status.json
ip -details -statistics link show can2

dbus -y com.victronenergy.genset.scheiber /Connected GetValue
dbus -y com.victronenergy.genset.scheiber /Start GetValue
dbus -y com.victronenergy.genset.scheiber /StatusCode GetValue

dbus -y com.victronenergy.generator.startstop1 /ManualStart GetValue
dbus -y com.victronenergy.generator.startstop1 /ManualStartTimer GetValue
dbus -y com.victronenergy.generator.startstop1 /RunningByCondition GetValue
```

Tank verification:

```bash
for s in \
  com.victronenergy.tank.scheiber_fresh \
  com.victronenergy.tank.scheiber_diesel1 \
  com.victronenergy.tank.scheiber_diesel2
do
  echo "===== $s ====="
  for p in Level Capacity Remaining; do
    printf '%-12s ' "$p:"
    dbus -y "$s" "/$p" GetValue
  done
done
```

Use `svc`, not `sv`, on the tested Venus image.
