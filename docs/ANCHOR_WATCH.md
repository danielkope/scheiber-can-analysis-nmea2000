# Smart Anchor Watch & Alarm Service (Victron Cerbo GX)

## Overview
The **Smart Anchor Watch Service** (`cerbo/anchor_watch_service.py`) provides an automated, multi-sensor vessel anchor watch system directly running on the Victron Cerbo GX. It interfaces with live NMEA 2000 sensors, D-Bus GPS, Telegram Bot API, and the Scheiber Multibloc V8 switchboard.

> [!IMPORTANT]
> **Relay Isolation Constraint**: Cerbo GX physical **Relay 1** is strictly reserved and **NEVER** toggled by the Anchor Watch service. All physical alarm illuminations are routed to the Scheiber switchboard (Channel 3: Deck Floodlights, Channel 4: Cockpit Lights).

---

## 1. Features & Capabilities

1. **Direct Geodesic Projection ("Reset to Heading")**:
   * Dynamically calculates the seabed anchor coordinates ahead of the bow:
     $$\text{Anchor Lat/Lon} = \text{Project}(\text{Boat GPS}, \text{Bearing}=\text{Heading}, \text{Distance}=\text{Chain Length})$$
2. **Interactive Telegram Quick Menu**:
   * Inline buttons under all status cards and alarms for one-tap operation.
3. **Multi-Sensor Safeguards**:
   * **Geofence Breach**: Alarms when vessel distance exceeds `Rode Length + Safety Margin`.
   * **GPS Jitter Suppression**: Filters temporary satellite drift.
4. **Physical Actions on Alarm**:
   * Automatically turns ON **Deck Floodlights** and **Cockpit Lights** via Scheiber D-Bus switchboard.

---

## 2. Interactive Telegram Keypad

When you text `/start`, `/menu`, or receive an alert, the Telegram bot presents the interactive quick menu:

```text
┌─────────────────────────┬─────────────────────────┐
│   ⚓ Drop (35m)          │   🔄 Reset to Heading   │
├─────────────────────────┼─────────────────────────┤
│   ➕ +5m Radius         │   ➖ -5m Radius         │
├─────────────────────────┼─────────────────────────┤
│   📊 Status & Map       │   💡 Deck Lights        │
├─────────────────────────┴─────────────────────────┤
│                 ❌ Disarm Alarm                   │
└───────────────────────────────────────────────────┘
```

### Alarm Notification Message:
When dragging is detected, the bot sends an urgent alert with one-tap action buttons:

```text
🚨 ANCHOR DRAG ALARM!

⚠️ Distance: 52.4 m (Limit: 45.0 m)
⚡ SOG: 1.2 kn | Heading: 285°
📍 Position: 43.50123°, 16.20456°
🔋 SoC: 88%

🗺️ View Vessel on Live Map

[ 💡 Deck Lights ON ]  [ 🔄 Reset to Heading ]
[ 🔕 Silence 15m    ]  [ ❌ Disarm Watch     ]
```

---

## 3. Configuration (`/data/conf/anchor_watch_config.json`)

To configure Telegram alerts:
```json
{
  "telegram_bot_token": "YOUR_TELEGRAM_BOT_TOKEN",
  "telegram_chat_id": "YOUR_TELEGRAM_CHAT_ID",
  "default_rode_m": 35.0,
  "default_safety_margin_m": 10.0,
  "depth_alarm_threshold_m": 2.5,
  "wind_squall_gust_kn": 25.0,
  "wind_shift_threshold_deg": 60.0,
  "turn_on_deck_lights_on_alarm": true,
  "deck_light_channel": 3,
  "cockpit_light_channel": 4
}
```

---

## 4. Commands Reference

| Command | Action |
|---|---|
| `/menu` or `/start` | Displays the interactive quick button menu. |
| `/status` or `/anchor` | Returns live anchor status, distance, heading, SOG, battery SoC, and map link. |
| `/anchor reset` | Re-calculates anchor coordinates from current GPS along current heading using existing rode length. |
| `/anchor reset <rode> <radius>` | Re-calculates anchor coordinates with custom rode length and alarm radius (e.g. `/anchor reset 50 45`). |
| `/anchor off` | Disarms the anchor watch. |
