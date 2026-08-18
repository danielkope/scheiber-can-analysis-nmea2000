# Live integration results

This page shows what a successful Scheiber -> Cerbo GX -> NMEA 2000 -> B&G Zeus3 installation can look like in practice.

The screenshots and field photo below are from the live-tested installation documented in this repository. Values naturally change with tank use and electrical load; use the labels, topology and consistency between displays as the acceptance criteria rather than expecting identical numbers.

## End-to-end tank result on B&G Zeus3

![B&G Zeus3 showing fresh water and both fuel tank values](images/integration/zeus3-tank-dashboard.jpg)

The Zeus3 can display the native Venus NMEA 2000 tank data after the correct incoming Fluid Level sources are selected in the B&G Network/Sources advanced data-source selection UI.

The live NMEA representation is PGN 127505 with Venus-assigned tank instances:

```text
6 = Fresh Water
7 = Diesel Tank 1 / Fuel Port
8 = Diesel Tank 2 / Fuel STBD
```

The important reproduction lesson is that **no 0/1/2 instance remapping was required**. Once PGN 127505 was already visible in Signal K loopback, the missing final step was B&G source selection.

## Cerbo GX tank integration

![Cerbo GX tank page showing Diesel Tank 1, Diesel Tank 2 and Fresh Water](images/integration/cerbo-tank-levels.jpg)

The bridge publishes native Victron tank services for all three Scheiber tanks. The Cerbo page should show three separate tanks with the configured capacities:

```text
Fresh Water    600 L
Diesel Tank 1  500 L
Diesel Tank 2  500 L
```

At one observed point the Cerbo showed approximately:

```text
Diesel Tank 1  62%   310 / 500 L
Diesel Tank 2  79%   395 / 500 L
Fresh Water    74%   444 / 600 L
```

The exact level may differ slightly from the Zeus3 picture because the photographs were not all captured at the exact same instant.

## Cerbo GX generator integration

![Cerbo GX native generator control backed by the Scheiber connected-genset bridge](images/integration/cerbo-generator-control.jpg)

A successful generator integration appears as a normal Victron generator device rather than a custom control screen. The bridge publishes `com.victronenergy.genset.scheiber`, which Victron's connected-genset manager uses for native manual start, autostart conditions, runtime and status handling.

Only the live-validated Scheiber command frames are transmitted by the production bridge:

```text
02460B88#01  START
02460B88#02  STOP
```

## Cerbo GX Scheiber house batteries

![Cerbo GX battery list showing individual Scheiber house-bank services](images/integration/cerbo-house-batteries.jpg)

The bridge can also expose the individual Scheiber house-battery streams as native Victron battery services. The screenshot demonstrates that the decoded voltage, current candidate and SoC values are visible through the standard Cerbo battery UI.

Keep the vessel's intended SmartShunt/system battery explicitly selected in Venus OS; the bridge deliberately avoids displacing the system-battery source when configuration is ambiguous.

## Acceptance checklist

A new installation should be considered end-to-end healthy when the following layers agree:

1. `can2` receives the proprietary Scheiber frames at 250 kbit/s without bus errors.
2. `/service/scheiber-gx` is up and its log/status file show fresh data.
3. The three native Victron tank services exist and expose sensible `/Level`, `/Capacity` and `/Remaining` values.
4. Signal K shows `tanks.freshWater.90`, `tanks.fuel.91` and `tanks.fuel.92` from `venus.*` sources.
5. Signal K also receives PGN 127505 loopback through `n2k-on-ve.can-socket`, observed on this installation as `.6/.7/.8`.
6. The Zeus3 has the correct incoming Fluid Level sources selected and displays the fresh-water and two fuel tanks.
7. The Cerbo UI presents generator control and the desired tank/battery devices through normal Victron pages.

If steps 1-5 pass but the Zeus3 is blank, do not immediately change the gateway. Check the B&G data-source selection first.

For the exact commands and troubleshooting decision tree, see [`SIGNALK_NMEA2000.md`](SIGNALK_NMEA2000.md) and [`CERBO_GX_INTEGRATION.md`](CERBO_GX_INTEGRATION.md).
