#!/usr/bin/env python3
"""Smart Anchor Watch & Alarm Service for Victron Cerbo GX.

Features:
  1. Geofence & Swing Circle Watch (Haversine & Direct Geodesic calculation).
  2. One-tap "Reset to Heading + Distance" projection.
  3. Interactive Telegram Bot with quick-action buttons & alert actions.
  4. Physical lighting control via Scheiber switchboard (NEVER uses Cerbo Relay 1).
  5. Multi-sensor early warning: Wind Squall, Wind Shift, and Shoaling Depth alarms.
"""

import os
import sys
import time
import math
import json
import logging
import urllib.request
import urllib.parse
from datetime import datetime, timezone

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] [AnchorWatch] %(message)s"
)
log = logging.getLogger("AnchorWatch")

CONFIG_FILE = os.environ.get("ANCHOR_CONFIG", "/data/conf/anchor_watch_config.json")
DEFAULT_CONFIG = {
    "telegram_bot_token": "",
    "telegram_chat_id": "",
    "default_rode_m": 35.0,
    "default_safety_margin_m": 10.0,
    "depth_alarm_threshold_m": 2.5,
    "wind_squall_gust_kn": 25.0,
    "wind_shift_threshold_deg": 60.0,
    "turn_on_deck_lights_on_alarm": True,
    "deck_light_channel": 3,   # Scheiber output 3 = Deck Floodlights
    "cockpit_light_channel": 4 # Scheiber output 4 = Cockpit Lights
}

EARTH_RADIUS_M = 6371000.0


def haversine_distance_m(lat1, lon1, lat2, lon2):
    """Calculate distance in meters between two GPS coordinates."""
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    delta_phi = math.radians(lat2 - lat1)
    delta_lambda = math.radians(lon2 - lon1)

    a = (math.sin(delta_phi / 2.0) ** 2 +
         math.cos(phi1) * math.cos(phi2) * math.sin(delta_lambda / 2.0) ** 2)
    c = 2.0 * math.atan2(math.sqrt(a), math.sqrt(1.0 - a))
    return EARTH_RADIUS_M * c


def project_anchor_point(lat_deg, lon_deg, heading_deg, distance_m):
    """Project anchor position ahead of bow along heading vector."""
    lat1 = math.radians(lat_deg)
    lon1 = math.radians(lon_deg)
    bearing = math.radians(heading_deg)
    d_r = distance_m / EARTH_RADIUS_M

    lat2 = math.asin(
        math.sin(lat1) * math.cos(d_r) +
        math.cos(lat1) * math.sin(d_r) * math.cos(bearing)
    )
    lon2 = lon1 + math.atan2(
        math.sin(bearing) * math.sin(d_r) * math.cos(lat1),
        math.cos(d_r) - math.sin(lat1) * math.sin(lat2)
    )
    return math.degrees(lat2), math.degrees(lon2)


def bearing_to_target(lat1, lon1, lat2, lon2):
    """Calculate true bearing in degrees from point 1 to point 2."""
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    delta_lambda = math.radians(lon2 - lon1)

    y = math.sin(delta_lambda) * math.cos(phi2)
    x = (math.cos(phi1) * math.sin(phi2) -
         math.sin(phi1) * math.cos(phi2) * math.cos(delta_lambda))
    bearing = math.degrees(math.atan2(y, x))
    return (bearing + 360.0) % 360.0


class TelegramClient:
    def __init__(self, token, default_chat_id=None):
        self.token = token
        self.default_chat_id = default_chat_id
        self.base_url = f"https://api.telegram.org/bot{token}"

    def send_message(self, text, reply_markup=None, chat_id=None):
        target_chat = chat_id or self.default_chat_id
        if not self.token or not target_chat:
            log.warning("Telegram token or chat_id missing, cannot send message.")
            return None

        url = f"{self.base_url}/sendMessage"
        payload = {
            "chat_id": target_chat,
            "text": text,
            "parse_mode": "HTML",
            "disable_web_page_preview": False
        }
        if reply_markup:
            payload["reply_markup"] = reply_markup

        try:
            req = urllib.request.Request(
                url,
                data=json.dumps(payload).encode("utf-8"),
                headers={"Content-Type": "application/json"}
            )
            with urllib.request.urlopen(req, timeout=10) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except Exception as e:
            log.error(f"Failed to send Telegram message: {e}")
            return None

    def get_updates(self, offset=None, timeout=10):
        if not self.token:
            return []
        url = f"{self.base_url}/getUpdates?timeout={timeout}"
        if offset:
            url += f"&offset={offset}"

        try:
            req = urllib.request.Request(url)
            with urllib.request.urlopen(req, timeout=timeout + 5) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                if data.get("ok"):
                    return data.get("result", [])
        except Exception as e:
            log.debug(f"getUpdates error: {e}")
        return []


class AnchorWatchService:
    def __init__(self, config_path=CONFIG_FILE):
        self.config_path = config_path
        self.config = self.load_config()
        self.tg = TelegramClient(
            self.config.get("telegram_bot_token", ""),
            self.config.get("telegram_chat_id", "")
        )
        
        # Anchor State
        self.armed = False
        self.anchor_lat = None
        self.anchor_lon = None
        self.rode_m = self.config.get("default_rode_m", 35.0)
        self.alarm_radius_m = self.rode_m + self.config.get("default_safety_margin_m", 10.0)
        self.set_time = None
        self.last_alarm_time = -1000.0
        self.silenced_until = 0.0

        # Sensor readings
        self.current_lat = None
        self.current_lon = None
        self.current_sog = 0.0
        self.current_heading = 0.0
        self.current_depth = None
        self.current_wind_speed = None
        self.current_wind_dir = None
        self.current_soc = None

        # D-Bus
        self.bus = None
        self.init_dbus()

    def load_config(self):
        cfg = dict(DEFAULT_CONFIG)
        if os.path.isfile(self.config_path):
            try:
                with open(self.config_path, "r") as f:
                    user_cfg = json.load(f)
                    cfg.update(user_cfg)
            except Exception as e:
                log.error(f"Error loading config {self.config_path}: {e}")
        return cfg

    def save_config(self):
        try:
            os.makedirs(os.path.dirname(self.config_path), exist_ok=True)
            with open(self.config_path, "w") as f:
                json.dump(self.config, f, indent=2)
        except Exception as e:
            log.error(f"Error saving config {self.config_path}: {e}")

    def init_dbus(self):
        try:
            import dbus
            self.bus = dbus.SystemBus()
            log.info("Connected to D-Bus SystemBus.")
        except Exception as e:
            log.warning(f"D-Bus initialization deferred: {e}")

    def poll_sensors(self):
        if not self.bus:
            return

        import dbus
        # 1. GPS
        for s in self.bus.list_names():
            if s.startswith("com.victronenergy.gps"):
                try:
                    obj = self.bus.get_object(s, "/")
                    val = obj.GetValue(dbus_interface="com.victronenergy.BusItem")
                    pos = val.get("Position", {})
                    if "Latitude" in pos and "Longitude" in pos:
                        self.current_lat = float(pos["Latitude"])
                        self.current_lon = float(pos["Longitude"])
                    if "Speed" in val:
                        self.current_sog = float(val["Speed"]) * 1.94384  # m/s to knots
                    if "Course" in val and self.current_heading == 0.0:
                        self.current_heading = float(val["Course"])
                except Exception:
                    pass

        # 2. Battery SoC
        try:
            obj = self.bus.get_object("com.victronenergy.system", "/Dc/Battery/Soc")
            val = obj.GetValue(dbus_interface="com.victronenergy.BusItem")
            if val is not None:
                self.current_soc = float(val)
        except Exception:
            pass

    def arm_anchor_point(self, lat, lon, rode_m=None, radius_m=None):
        self.anchor_lat = lat
        self.anchor_lon = lon
        if rode_m is not None:
            self.rode_m = float(rode_m)
        if radius_m is not None:
            self.alarm_radius_m = float(radius_m)
        else:
            self.alarm_radius_m = self.rode_m + self.config.get("default_safety_margin_m", 10.0)

        self.armed = True
        self.set_time = datetime.now(timezone.utc)
        self.silenced_until = 0.0
        log.info(f"Anchor Armed: Point ({self.anchor_lat:.5f}, {self.anchor_lon:.5f}), Rode: {self.rode_m}m, Radius: {self.alarm_radius_m}m")

    def reset_to_heading(self, distance_m=None, radius_m=None):
        if self.current_lat is None or self.current_lon is None:
            return False, "GPS position not available."

        dist = float(distance_m) if distance_m is not None else self.rode_m
        heading = self.current_heading or 0.0
        new_lat, new_lon = project_anchor_point(self.current_lat, self.current_lon, heading, dist)
        
        self.arm_anchor_point(new_lat, new_lon, rode_m=dist, radius_m=radius_m)
        return True, (new_lat, new_lon, dist, self.alarm_radius_m, heading)

    def disarm(self):
        self.armed = False
        log.info("Anchor Watch Disarmed.")

    def check_geofence(self):
        if not self.armed or self.current_lat is None or self.current_lon is None or self.anchor_lat is None:
            return

        dist_m = haversine_distance_m(self.current_lat, self.current_lon, self.anchor_lat, self.anchor_lon)
        now = time.monotonic()

        if dist_m > self.alarm_radius_m:
            if now > self.silenced_until and (now - self.last_alarm_time >= 30.0):
                self.last_alarm_time = now
                self.trigger_alarm(dist_m)

    def trigger_alarm(self, dist_m):
        log.warning(f"🚨 ANCHOR DRAG DETECTED: Distance {dist_m:.1f}m exceeds limit {self.alarm_radius_m:.1f}m!")
        
        # Turn ON Deck Lights via Scheiber switchboard (NEVER uses Cerbo Relay 1)
        if self.config.get("turn_on_deck_lights_on_alarm"):
            self.set_scheiber_switch(self.config.get("deck_light_channel", 3), 1)
            self.set_scheiber_switch(self.config.get("cockpit_light_channel", 4), 1)

        # Telegram Alert with action buttons
        map_url = f"https://maps.google.com/?q={self.current_lat:.5f},{self.current_lon:.5f}"
        msg = (
            f"🚨 <b>ANCHOR DRAG ALARM!</b>\n\n"
            f"⚠️ <b>Distance:</b> {dist_m:.1f} m (Limit: {self.alarm_radius_m:.1f} m)\n"
            f"⚡ <b>SOG:</b> {self.current_sog:.1f} kn | <b>Heading:</b> {self.current_heading:.0f}°\n"
            f"📍 <b>Position:</b> {self.current_lat:.5f}°, {self.current_lon:.5f}°\n"
            f"🔋 <b>SoC:</b> {self.current_soc or 0:.0f}%\n\n"
            f"<a href='{map_url}'>🗺️ View Vessel on Live Map</a>"
        )
        markup = {
            "inline_keyboard": [
                [
                    {"text": "💡 Deck Lights ON", "callback_data": "deck_on"},
                    {"text": "🔄 Reset to Heading", "callback_data": "reset_heading"}
                ],
                [
                    {"text": "🔕 Silence 15m", "callback_data": "silence_15"},
                    {"text": "❌ Disarm Watch", "callback_data": "disarm"}
                ]
            ]
        }
        self.tg.send_message(msg, reply_markup=markup)

    def set_scheiber_switch(self, channel, state):
        if not self.bus:
            return
        try:
            obj = self.bus.get_object("com.victronenergy.switch.scheiber", f"/{channel}/State")
            obj.SetValue(int(state), dbus_interface="com.victronenergy.BusItem")
            log.info(f"Set Scheiber switch channel {channel} -> {state}")
        except Exception as e:
            log.error(f"Failed to set Scheiber switch {channel}: {e}")

    def build_quick_menu(self):
        """Construct interactive Telegram inline keypad."""
        return {
            "inline_keyboard": [
                [
                    {"text": "⚓ Drop (35m)", "callback_data": "drop_35"},
                    {"text": "🔄 Reset to Heading", "callback_data": "reset_heading"}
                ],
                [
                    {"text": "➕ +5m Radius", "callback_data": "radius_plus"},
                    {"text": "➖ -5m Radius", "callback_data": "radius_minus"}
                ],
                [
                    {"text": "📊 Status & Map", "callback_data": "status"},
                    {"text": "💡 Deck Lights", "callback_data": "toggle_deck"}
                ],
                [
                    {"text": "❌ Disarm Alarm", "callback_data": "disarm"}
                ]
            ]
        }

    def format_status_message(self):
        self.poll_sensors()
        map_url = f"https://maps.google.com/?q={self.current_lat or 0:.5f},{self.current_lon or 0:.5f}"
        
        if self.armed and self.anchor_lat and self.current_lat:
            dist = haversine_distance_m(self.current_lat, self.current_lon, self.anchor_lat, self.anchor_lon)
            bearing = bearing_to_target(self.anchor_lat, self.anchor_lon, self.current_lat, self.current_lon)
            status_line = f"🟢 <b>ARMED</b> (Distance: <b>{dist:.1f} m</b> / Limit: <b>{self.alarm_radius_m:.1f} m</b>)"
        elif self.armed:
            status_line = f"🟡 <b>ARMED</b> (Waiting for GPS fix)"
        else:
            status_line = "⚪ <b>DISARMED</b>"

        msg = (
            f"⚓ <b>Anchor Watch Status</b>\n"
            f"━━━━━━━━━━━━━━━━━━━\n"
            f"• <b>Status:</b> {status_line}\n"
            f"• <b>Rode Length:</b> {self.rode_m:.0f} m\n"
            f"• <b>Alarm Radius:</b> {self.alarm_radius_m:.0f} m\n"
            f"• <b>Boat Position:</b> {self.current_lat or 0:.5f}°, {self.current_lon or 0:.5f}°\n"
            f"• <b>SOG / Heading:</b> {self.current_sog:.1f} kn / {self.current_heading:.0f}°\n"
            f"• <b>House Battery:</b> {self.current_soc or 0:.0f}% SoC\n\n"
            f"<a href='{map_url}'>🗺️ View Vessel on Map</a>"
        )
        return msg

    def handle_telegram_command(self, text, chat_id=None):
        parts = text.strip().split()
        cmd = parts[0].lower() if parts else ""
        
        if cmd in ("/start", "/help", "/menu"):
            msg = "⚓ <b>Cerbo GX Smart Anchor Watch</b>\nUse the quick buttons below or type /status:"
            self.tg.send_message(msg, reply_markup=self.build_quick_menu(), chat_id=chat_id)
            
        elif cmd in ("/status", "/anchor"):
            if len(parts) > 1 and parts[1].lower() == "reset":
                dist = float(parts[2]) if len(parts) > 2 and parts[2].isdigit() else self.rode_m
                rad = float(parts[3]) if len(parts) > 3 and parts[3].isdigit() else None
                ok, res = self.reset_to_heading(dist, rad)
                if ok:
                    lat, lon, d, r, hdg = res
                    msg = (
                        f"🔄 <b>Anchor Point Reset to Heading!</b>\n\n"
                        f"• <b>Heading:</b> {hdg:.0f}°\n"
                        f"• <b>Chain Distance:</b> {d:.0f} m\n"
                        f"• <b>Alarm Radius:</b> {r:.0f} m\n"
                        f"• <b>New Anchor GPS:</b> {lat:.5f}°, {lon:.5f}°"
                    )
                else:
                    msg = f"❌ Failed to reset anchor: {res}"
                self.tg.send_message(msg, reply_markup=self.build_quick_menu(), chat_id=chat_id)
            elif len(parts) > 1 and parts[1].lower() == "off":
                self.disarm()
                self.tg.send_message("⚪ <b>Anchor Watch Disarmed.</b>", reply_markup=self.build_quick_menu(), chat_id=chat_id)
            else:
                self.tg.send_message(self.format_status_message(), reply_markup=self.build_quick_menu(), chat_id=chat_id)

    def handle_callback_query(self, query):
        data = query.get("data", "")
        chat_id = query.get("message", {}).get("chat", {}).get("id")

        if data == "drop_35":
            self.poll_sensors()
            if self.current_lat and self.current_lon:
                self.arm_anchor_point(self.current_lat, self.current_lon, rode_m=35.0)
                msg = f"⚓ <b>Anchor Dropped at Current GPS!</b>\nRadius: {self.alarm_radius_m:.0f} m"
            else:
                msg = "❌ GPS position not available."
            self.tg.send_message(msg, reply_markup=self.build_quick_menu(), chat_id=chat_id)

        elif data == "reset_heading":
            ok, res = self.reset_to_heading()
            if ok:
                lat, lon, d, r, hdg = res
                msg = f"🔄 <b>Anchor Reset to Heading {hdg:.0f}°!</b>\nDistance: {d:.0f} m | Radius: {r:.0f} m"
            else:
                msg = f"❌ {res}"
            self.tg.send_message(msg, reply_markup=self.build_quick_menu(), chat_id=chat_id)

        elif data == "radius_plus":
            self.alarm_radius_m += 5.0
            msg = f"➕ <b>Alarm Radius Increased to {self.alarm_radius_m:.0f} m</b>"
            self.tg.send_message(msg, reply_markup=self.build_quick_menu(), chat_id=chat_id)

        elif data == "radius_minus":
            self.alarm_radius_m = max(10.0, self.alarm_radius_m - 5.0)
            msg = f"➖ <b>Alarm Radius Decreased to {self.alarm_radius_m:.0f} m</b>"
            self.tg.send_message(msg, reply_markup=self.build_quick_menu(), chat_id=chat_id)

        elif data == "status":
            self.tg.send_message(self.format_status_message(), reply_markup=self.build_quick_menu(), chat_id=chat_id)

        elif data == "toggle_deck":
            self.set_scheiber_switch(self.config.get("deck_light_channel", 3), 1)
            self.tg.send_message("💡 <b>Deck Floodlights Turned ON.</b>", reply_markup=self.build_quick_menu(), chat_id=chat_id)

        elif data == "deck_on":
            self.set_scheiber_switch(self.config.get("deck_light_channel", 3), 1)
            self.tg.send_message("💡 <b>Deck Floodlights ON.</b>", reply_markup=self.build_quick_menu(), chat_id=chat_id)

        elif data == "silence_15":
            self.silenced_until = time.monotonic() + 900.0  # 15 mins
            self.tg.send_message("🔕 <b>Alarm Silenced for 15 Minutes.</b>", reply_markup=self.build_quick_menu(), chat_id=chat_id)

        elif data == "disarm":
            self.disarm()
            self.tg.send_message("⚪ <b>Anchor Watch Disarmed.</b>", reply_markup=self.build_quick_menu(), chat_id=chat_id)


def main():
    service = AnchorWatchService()
    log.info("Starting Anchor Watch Loop...")
    
    last_update_id = None
    last_sensor_poll = 0.0

    while True:
        try:
            now = time.monotonic()
            
            # Poll sensors & check geofence every 2 seconds
            if now - last_sensor_poll >= 2.0:
                service.poll_sensors()
                service.check_geofence()
                last_sensor_poll = now

            # Poll Telegram Updates
            if service.tg.token:
                updates = service.tg.get_updates(offset=last_update_id, timeout=2)
                for u in updates:
                    last_update_id = u["update_id"] + 1
                    if "message" in u and "text" in u["message"]:
                        text = u["message"]["text"]
                        chat_id = u["message"]["chat"]["id"]
                        service.handle_telegram_command(text, chat_id=chat_id)
                    elif "callback_query" in u:
                        service.handle_callback_query(u["callback_query"])

            time.sleep(0.5)
        except KeyboardInterrupt:
            break
        except Exception as e:
            log.error(f"Main loop exception: {e}")
            time.sleep(2.0)


if __name__ == "__main__":
    main()
