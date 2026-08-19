#!/usr/bin/env python3
"""Smart Anchor Watch & Alarm Service for Victron Cerbo GX.

Features:
  1. Geofence & Swing Circle Watch (Haversine & Direct Geodesic calculation).
  2. One-tap "Reset to Heading + Distance" projection.
  3. Continuous Breadcrumb Track & Wind (TWS/TWD) History Recording.
  4. Real-time NMEA 2000 listener (Wind PGN 130306, Depth PGN 128267, Heading PGN 127250, GPS PGN 129029).
  5. Vector Cairo Map Rendering with concentric rings, swing trail, and live Wind Rose HUD.
  6. Interactive Telegram Bot with dynamic quick-action buttons & map photo dispatch.
  7. Physical lighting control via Scheiber switchboard (NEVER uses Cerbo Relay 1).
"""

import os
import sys
import time
import math
import json
import uuid
import io
import socket
import struct
import threading
import logging
import urllib.request
import urllib.parse
from datetime import datetime, timezone

try:
    import cairo
    HAVE_CAIRO = True
except ImportError:
    HAVE_CAIRO = False

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] [AnchorWatch] %(message)s"
)
log = logging.getLogger("AnchorWatch")

CONFIG_FILE = os.environ.get("ANCHOR_CONFIG", "/data/conf/anchor_watch_config.json")
DEFAULT_CONFIG = {
    "telegram_bot_token": "",
    "telegram_chat_id": "",
    "default_rode_m": 50.0,
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


def wind_direction_cardinal(deg):
    """Convert degrees to cardinal direction string."""
    if deg is None:
        return "N/A"
    cardinals = ["N", "NNE", "NE", "ENE", "E", "ESE", "SE", "SSE",
                 "S", "SSW", "SW", "WSW", "W", "WNW", "NW", "NNW"]
    idx = int((deg + 11.25) / 22.5) % 16
    return cardinals[idx]


def render_anchor_map_png(anchor_lat, anchor_lon, alarm_radius_m, track_points, current_lat, current_lon, current_heading=0.0, current_sog=0.0, current_soc=None, current_wind_speed=None, current_wind_dir=None, current_depth=None, wind_history=None):
    """Render high-resolution dark nautical anchor watch map as PNG with Wind Rose."""
    if not HAVE_CAIRO:
        return None

    width, height = 850, 850
    surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, width, height)
    ctx = cairo.Context(surface)

    R = 6371000.0
    lat_rad = math.radians(anchor_lat)

    def gps_to_xy(lat, lon):
        d_lat = math.radians(lat - anchor_lat)
        d_lon = math.radians(lon - anchor_lon)
        north_m = d_lat * R
        east_m = d_lon * R * math.cos(lat_rad)
        return east_m, north_m

    all_x = [0.0]
    all_y = [0.0]
    for pt in track_points:
        ex, ny = gps_to_xy(pt["lat"], pt["lon"])
        all_x.append(ex)
        all_y.append(ny)
    if current_lat and current_lon:
        cx, cy = gps_to_xy(current_lat, current_lon)
        all_x.append(cx)
        all_y.append(cy)

    max_dist = max(alarm_radius_m * 1.35, max(math.hypot(x, y) for x, y in zip(all_x, all_y)) * 1.25, 30.0)
    scale = (min(width, height) / 2.0 - 55.0) / max_dist

    center_x = width / 2.0
    center_y = height / 2.0 + 15.0

    def to_pixel(east_m, north_m):
        return center_x + east_m * scale, center_y - north_m * scale

    # 1. Background
    ctx.set_source_rgb(0.04, 0.07, 0.12)
    ctx.paint()

    # 2. Concentric Distance Rings
    ring_interval = 10.0 if max_dist <= 60 else (20.0 if max_dist <= 150 else 50.0)
    r = ring_interval
    while r <= max_dist:
        ctx.set_source_rgba(0.2, 0.35, 0.5, 0.25)
        ctx.set_line_width(1.0)
        ctx.arc(center_x, center_y, r * scale, 0, 2 * math.pi)
        ctx.stroke()

        ctx.select_font_face("Sans", cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_NORMAL)
        ctx.set_font_size(11)
        ctx.set_source_rgba(0.4, 0.6, 0.8, 0.6)
        ctx.move_to(center_x + 6, center_y - r * scale + 12)
        ctx.show_text(f"{r:.0f}m")
        r += ring_interval

    # 3. Crosshairs
    ctx.set_source_rgba(0.2, 0.35, 0.5, 0.3)
    ctx.set_line_width(1.0)
    ctx.move_to(center_x, 30)
    ctx.line_to(center_x, height - 30)
    ctx.move_to(30, center_y)
    ctx.line_to(width - 30, center_y)
    ctx.stroke()

    # 4. Safe Alarm Radius (Dashed Green/Cyan Circle)
    alarm_px = alarm_radius_m * scale
    ctx.set_source_rgba(0.1, 0.8, 0.4, 0.08)
    ctx.arc(center_x, center_y, alarm_px, 0, 2 * math.pi)
    ctx.fill()

    ctx.set_source_rgba(0.1, 0.9, 0.5, 0.85)
    ctx.set_line_width(2.0)
    ctx.set_dash([6.0, 4.0])
    ctx.arc(center_x, center_y, alarm_px, 0, 2 * math.pi)
    ctx.stroke()
    ctx.set_dash([])

    # 5. Breadcrumb Track History
    if len(track_points) > 1:
        ctx.set_line_width(2.5)
        for i in range(len(track_points) - 1):
            p1 = track_points[i]
            p2 = track_points[i + 1]
            x1, y1 = to_pixel(*gps_to_xy(p1["lat"], p1["lon"]))
            x2, y2 = to_pixel(*gps_to_xy(p2["lat"], p2["lon"]))

            progress = (i + 1) / len(track_points)
            ctx.set_source_rgba(0.2, 0.6 + 0.4 * progress, 1.0, 0.3 + 0.6 * progress)
            ctx.move_to(x1, y1)
            ctx.line_to(x2, y2)
            ctx.stroke()

        for p in track_points:
            px, py = to_pixel(*gps_to_xy(p["lat"], p["lon"]))
            ctx.set_source_rgba(0.3, 0.8, 1.0, 0.6)
            ctx.arc(px, py, 2.0, 0, 2 * math.pi)
            ctx.fill()

    # 6. Rode Line
    if current_lat and current_lon:
        cx, cy = to_pixel(*gps_to_xy(current_lat, current_lon))
        ctx.set_source_rgba(1.0, 0.85, 0.2, 0.6)
        ctx.set_line_width(1.5)
        ctx.set_dash([4.0, 3.0])
        ctx.move_to(center_x, center_y)
        ctx.line_to(cx, cy)
        ctx.stroke()
        ctx.set_dash([])

    # 7. Anchor Marker at Center (0,0)
    ctx.set_source_rgb(1.0, 0.3, 0.2)
    ctx.arc(center_x, center_y, 7.0, 0, 2 * math.pi)
    ctx.fill()
    ctx.set_source_rgb(1.0, 1.0, 1.0)
    ctx.set_line_width(2.0)
    ctx.arc(center_x, center_y, 7.0, 0, 2 * math.pi)
    ctx.stroke()

    ctx.select_font_face("Sans", cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_BOLD)
    ctx.set_font_size(13)
    ctx.set_source_rgb(1.0, 0.4, 0.3)
    ctx.move_to(center_x + 10, center_y + 16)
    ctx.show_text("⚓ ANCHOR")

    # 8. Current Vessel Position & Hull
    if current_lat and current_lon:
        cx, cy = to_pixel(*gps_to_xy(current_lat, current_lon))
        hdg_rad = math.radians(current_heading)

        boat_len = 16.0
        boat_width = 8.0
        
        tip_x = cx + boat_len * math.sin(hdg_rad)
        tip_y = cy - boat_len * math.cos(hdg_rad)
        
        port_x = cx - boat_width * math.cos(hdg_rad) - (boat_len * 0.4) * math.sin(hdg_rad)
        port_y = cy - boat_width * math.sin(hdg_rad) + (boat_len * 0.4) * math.cos(hdg_rad)
        
        stbd_x = cx + boat_width * math.cos(hdg_rad) - (boat_len * 0.4) * math.sin(hdg_rad)
        stbd_y = cy + boat_width * math.sin(hdg_rad) + (boat_len * 0.4) * math.cos(hdg_rad)

        ctx.set_source_rgba(0.1, 0.8, 1.0, 0.9)
        ctx.move_to(tip_x, tip_y)
        ctx.line_to(port_x, port_y)
        ctx.line_to(stbd_x, stbd_y)
        ctx.close_path()
        ctx.fill()
        
        ctx.set_source_rgb(1.0, 1.0, 1.0)
        ctx.set_line_width(1.5)
        ctx.move_to(tip_x, tip_y)
        ctx.line_to(port_x, port_y)
        ctx.line_to(stbd_x, stbd_y)
        ctx.close_path()
        ctx.stroke()

        ctx.set_source_rgb(1.0, 1.0, 1.0)
        ctx.arc(cx, cy, 3.0, 0, 2 * math.pi)
        ctx.fill()

    # 9. Top HUD Overlay Header
    cur_dist = math.hypot(*gps_to_xy(current_lat, current_lon)) if (current_lat and current_lon) else 0.0
    ctx.set_source_rgba(0.02, 0.05, 0.09, 0.85)
    ctx.rectangle(15, 15, width - 30, 80)
    ctx.fill()
    ctx.set_source_rgba(0.2, 0.4, 0.6, 0.5)
    ctx.set_line_width(1.0)
    ctx.rectangle(15, 15, width - 30, 80)
    ctx.stroke()

    ctx.select_font_face("Sans", cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_BOLD)
    ctx.set_font_size(15)
    ctx.set_source_rgb(0.2, 0.9, 0.6)
    ctx.move_to(30, 42)
    ctx.show_text(f"DISTANCE: {cur_dist:.1f} m  |  LIMIT: {alarm_radius_m:.0f} m")

    ctx.set_font_size(13)
    ctx.set_source_rgb(0.8, 0.9, 1.0)
    ctx.move_to(30, 66)
    soc_str = f"{current_soc:.0f}%" if current_soc is not None else "N/A"
    depth_str = f"{current_depth:.1f}m" if current_depth is not None else "N/A"
    wind_str = f"{current_wind_speed:.1f}kn {wind_direction_cardinal(current_wind_dir)} ({current_wind_dir:.0f}°)" if (current_wind_speed is not None and current_wind_dir is not None) else "N/A"
    ctx.show_text(f"WIND: {wind_str}   DEPTH: {depth_str}   HDG: {current_heading:.0f}°   BATTERY: {soc_str}")

    ctx.set_font_size(11)
    ctx.set_source_rgba(0.5, 0.7, 0.9, 0.8)
    ctx.move_to(30, 85)
    ctx.show_text(f"SOG: {current_sog:.1f} kn   TRACK POINTS: {len(track_points)}")

    # 10. Floating Wind Rose in Top Right
    if current_wind_dir is not None:
        wr_x = width - 75
        wr_y = 155
        wr_rad = 42.0

        ctx.set_source_rgba(0.02, 0.05, 0.09, 0.85)
        ctx.arc(wr_x, wr_y, wr_rad + 8, 0, 2 * math.pi)
        ctx.fill()
        ctx.set_source_rgba(0.2, 0.4, 0.6, 0.5)
        ctx.set_line_width(1.0)
        ctx.arc(wr_x, wr_y, wr_rad + 8, 0, 2 * math.pi)
        ctx.stroke()

        # Wind Rose Compass Ring
        ctx.set_source_rgba(0.3, 0.5, 0.7, 0.4)
        ctx.arc(wr_x, wr_y, wr_rad, 0, 2 * math.pi)
        ctx.stroke()

        # Cardinal markers
        ctx.set_font_size(10)
        ctx.set_source_rgba(0.6, 0.8, 1.0, 0.9)
        ctx.move_to(wr_x - 4, wr_y - wr_rad + 11)
        ctx.show_text("N")
        ctx.move_to(wr_x + wr_rad - 12, wr_y + 4)
        ctx.show_text("E")
        ctx.move_to(wr_x - 4, wr_y + wr_rad - 3)
        ctx.show_text("S")
        ctx.move_to(wr_x - wr_rad + 3, wr_y + 4)
        ctx.show_text("W")

        # Wind Direction Arrow (Pointing in direction wind is blowing TO)
        w_rad = math.radians(current_wind_dir)
        w_tip_x = wr_x + (wr_rad - 12) * math.sin(w_rad)
        w_tip_y = wr_y - (wr_rad - 12) * math.cos(w_rad)
        w_base_x = wr_x - (wr_rad - 18) * math.sin(w_rad)
        w_base_y = wr_y + (wr_rad - 18) * math.cos(w_rad)

        ctx.set_source_rgba(0.0, 0.9, 1.0, 0.9)
        ctx.set_line_width(3.0)
        ctx.move_to(w_base_x, w_base_y)
        ctx.line_to(w_tip_x, w_tip_y)
        ctx.stroke()

        # Arrow head
        arr_size = 8.0
        ctx.set_source_rgba(0.0, 0.9, 1.0, 0.9)
        ctx.move_to(w_tip_x, w_tip_y)
        ctx.line_to(w_tip_x - arr_size * math.sin(w_rad - 0.5), w_tip_y + arr_size * math.cos(w_rad - 0.5))
        ctx.line_to(w_tip_x - arr_size * math.sin(w_rad + 0.5), w_tip_y + arr_size * math.cos(w_rad + 0.5))
        ctx.close_path()
        ctx.fill()

        # Wind Speed in center of rose
        ctx.set_font_size(10)
        ctx.set_source_rgb(1.0, 1.0, 1.0)
        ws_label = f"{current_wind_speed:.0f}k" if current_wind_speed is not None else ""
        ctx.move_to(wr_x - 8, wr_y + 4)
        ctx.show_text(ws_label)

    # 11. Bottom Timestamp Footer
    now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    ctx.set_font_size(11)
    ctx.set_source_rgba(0.5, 0.6, 0.7, 0.8)
    ctx.move_to(25, height - 18)
    ctx.show_text(f"Cerbo GX Smart Anchor Watch • {now_str} • Lat: {current_lat or 0:.5f}°, Lon: {current_lon or 0:.5f}°")

    buf = io.BytesIO()
    surface.write_to_png(buf)
    return buf.getvalue()


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

    def send_photo(self, photo_bytes, caption="", reply_markup=None, chat_id=None):
        target_chat = chat_id or self.default_chat_id
        if not self.token or not target_chat:
            return None

        boundary = f"----WebKitFormBoundary{uuid.uuid4().hex}"
        body = bytearray()

        body.extend(f"--{boundary}\r\n".encode("utf-8"))
        body.extend(f'Content-Disposition: form-data; name="chat_id"\r\n\r\n{target_chat}\r\n'.encode("utf-8"))

        if caption:
            body.extend(f"--{boundary}\r\n".encode("utf-8"))
            body.extend(f'Content-Disposition: form-data; name="caption"\r\n\r\n{caption}\r\n'.encode("utf-8"))
            body.extend(f"--{boundary}\r\n".encode("utf-8"))
            body.extend(b'Content-Disposition: form-data; name="parse_mode"\r\n\r\nHTML\r\n')

        if reply_markup:
            body.extend(f"--{boundary}\r\n".encode("utf-8"))
            body.extend(f'Content-Disposition: form-data; name="reply_markup"\r\n\r\n{json.dumps(reply_markup)}\r\n'.encode("utf-8"))

        body.extend(f"--{boundary}\r\n".encode("utf-8"))
        body.extend(b'Content-Disposition: form-data; name="photo"; filename="anchor_map.png"\r\n')
        body.extend(b"Content-Type: image/png\r\n\r\n")
        body.extend(photo_bytes)
        body.extend(b"\r\n")

        body.extend(f"--{boundary}--\r\n".encode("utf-8"))

        url = f"{self.base_url}/sendPhoto"
        try:
            req = urllib.request.Request(
                url,
                data=bytes(body),
                headers={"Content-Type": f"multipart/form-data; boundary={boundary}"}
            )
            with urllib.request.urlopen(req, timeout=15) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except Exception as e:
            log.error(f"Failed to send Telegram photo: {e}")
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
    def __init__(self, config_path=CONFIG_FILE, can_interface="can1"):
        self.config_path = config_path
        self.can_interface = can_interface
        self.config = self.load_config()
        self.tg = TelegramClient(
            self.config.get("telegram_bot_token", ""),
            self.config.get("telegram_chat_id", "")
        )
        
        # Anchor State
        self.armed = False
        self.anchor_lat = None
        self.anchor_lon = None
        self.rode_m = self.config.get("default_rode_m", 50.0)
        self.alarm_radius_m = self.rode_m + self.config.get("default_safety_margin_m", 10.0)
        self.set_time = None
        self.last_alarm_time = -1000.0
        self.silenced_until = 0.0
        
        # History Buffers
        self.track_points = []
        self.wind_history = []
        self.last_track_record_time = 0.0

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

        # N2K Listener Thread
        self.can_thread_running = False
        self.start_n2k_listener()

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

    def init_dbus(self):
        try:
            import dbus
            self.bus = dbus.SystemBus()
            log.info("Connected to D-Bus SystemBus.")
        except Exception as e:
            log.warning(f"D-Bus initialization deferred: {e}")

    def start_n2k_listener(self):
        self.can_thread_running = True
        t = threading.Thread(target=self._n2k_reader_loop, daemon=True)
        t.start()

    def _n2k_reader_loop(self):
        try:
            s = socket.socket(socket.AF_CAN, socket.SOCK_RAW, socket.CAN_RAW)
            s.bind((self.can_interface,))
            s.settimeout(2.0)
            log.info(f"N2K CAN listener active on {self.can_interface}")
        except Exception as e:
            log.warning(f"Could not bind to {self.can_interface}: {e}")
            return

        while self.can_thread_running:
            try:
                cf, addr = s.recvfrom(16)
                can_id, can_dlc, data = struct.unpack('<IB3x8s', cf)
                can_id &= 0x1FFFFFFF
                pgn = (can_id >> 8) & 0x1FFFF
                if (pgn & 0xFF00) < 0xF000:
                    pgn = pgn & 0x1FF00

                # 1. PGN 130306: Wind Data
                if pgn == 130306:
                    speed_raw = struct.unpack('<H', data[1:3])[0]
                    angle_raw = struct.unpack('<H', data[3:5])[0]
                    ref = data[5] & 0x07
                    if speed_raw != 0xFFFF:
                        self.current_wind_speed = (speed_raw * 0.01) * 1.94384
                    if angle_raw != 0xFFFF:
                        angle_deg = math.degrees(angle_raw * 0.0001)
                        if ref == 0:  # True North (TWD)
                            self.current_wind_dir = angle_deg
                        elif ref in (2, 3):  # Apparent or True Boat relative
                            self.current_wind_dir = (self.current_heading + angle_deg) % 360.0

                # 2. PGN 128267: Water Depth
                elif pgn == 128267:
                    depth_raw = struct.unpack('<I', data[1:5])[0]
                    if depth_raw != 0xFFFFFFFF:
                        self.current_depth = depth_raw * 0.01

                # 3. PGN 127250: Vessel Heading
                elif pgn == 127250:
                    hdg_raw = struct.unpack('<H', data[1:3])[0]
                    if hdg_raw != 0xFFFF:
                        self.current_heading = math.degrees(hdg_raw * 0.0001)

            except socket.timeout:
                pass
            except Exception as e:
                log.debug(f"N2K reader exception: {e}")
                time.sleep(0.5)

    def poll_sensors(self):
        if not self.bus:
            return

        import dbus
        best_sats = -1
        for s in self.bus.list_names():
            if s.startswith("com.victronenergy.gps"):
                try:
                    obj = self.bus.get_object(s, "/")
                    val = obj.GetValue(dbus_interface="com.victronenergy.BusItem")
                    if isinstance(val, dict):
                        lat = val.get("Position/Latitude") or val.get("Position", {}).get("Latitude")
                        lon = val.get("Position/Longitude") or val.get("Position", {}).get("Longitude")
                        fix = val.get("Fix", 1)
                        sats = int(val.get("NrOfSatellites", 0))

                        if lat is not None and lon is not None and int(fix) > 0 and sats >= best_sats:
                            self.current_lat = float(lat)
                            self.current_lon = float(lon)
                            best_sats = sats
                            if "Speed" in val and val["Speed"] is not None:
                                self.current_sog = float(val["Speed"]) * 1.94384
                            if "Course" in val and val["Course"] is not None and self.current_heading == 0.0:
                                self.current_heading = float(val["Course"])
                except Exception as e:
                    log.debug(f"Error polling GPS service {s}: {e}")

        # Battery SoC
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
        self.track_points = []
        self.wind_history = []
        if self.current_lat and self.current_lon:
            self.track_points.append({"lat": self.current_lat, "lon": self.current_lon, "time": time.time()})
        log.info(f"Anchor Armed: Point ({self.anchor_lat:.5f}, {self.anchor_lon:.5f}), Rode: {self.rode_m}m, Radius: {self.alarm_radius_m}m")

    def reset_to_heading(self, distance_m=None, radius_m=None):
        self.poll_sensors()
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

        now = time.monotonic()

        # Record breadcrumbs & wind sample every 10s
        if now - self.last_track_record_time >= 10.0:
            record = True
            if self.track_points:
                last_pt = self.track_points[-1]
                d = haversine_distance_m(self.current_lat, self.current_lon, last_pt["lat"], last_pt["lon"])
                if d < 1.5 and (now - self.last_track_record_time < 60.0):
                    record = False
            if record:
                self.track_points.append({"lat": self.current_lat, "lon": self.current_lon, "time": time.time()})
                if self.current_wind_speed is not None and self.current_wind_dir is not None:
                    self.wind_history.append({"tws": self.current_wind_speed, "twd": self.current_wind_dir, "time": time.time()})
                if len(self.track_points) > 1500:
                    self.track_points.pop(0)
                if len(self.wind_history) > 1500:
                    self.wind_history.pop(0)
                self.last_track_record_time = now

        dist_m = haversine_distance_m(self.current_lat, self.current_lon, self.anchor_lat, self.anchor_lon)

        if dist_m > self.alarm_radius_m:
            if now > self.silenced_until and (now - self.last_alarm_time >= 30.0):
                self.last_alarm_time = now
                self.trigger_alarm(dist_m)

    def trigger_alarm(self, dist_m):
        log.warning(f"🚨 ANCHOR DRAG DETECTED: Distance {dist_m:.1f}m exceeds limit {self.alarm_radius_m:.1f}m!")
        
        if self.config.get("turn_on_deck_lights_on_alarm"):
            self.set_scheiber_switch(self.config.get("deck_light_channel", 3), 1)
            self.set_scheiber_switch(self.config.get("cockpit_light_channel", 4), 1)

        map_url = f"https://maps.google.com/?q={self.current_lat:.5f},{self.current_lon:.5f}"
        wind_cardinal = wind_direction_cardinal(self.current_wind_dir)
        msg = (
            f"🚨 <b>ANCHOR DRAG ALARM!</b>\n\n"
            f"⚠️ <b>Distance:</b> {dist_m:.1f} m (Limit: {self.alarm_radius_m:.1f} m)\n"
            f"💨 <b>Wind:</b> {self.current_wind_speed or 0:.1f} kn {wind_cardinal} ({self.current_wind_dir or 0:.0f}°)\n"
            f"🌊 <b>Depth:</b> {self.current_depth or 0:.1f} m\n"
            f"⚡ <b>SOG / Heading:</b> {self.current_sog:.1f} kn / {self.current_heading:.0f}°\n"
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

        png = self.render_map()
        if png:
            self.tg.send_photo(png, caption=msg, reply_markup=markup)
        else:
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

    def render_map(self):
        if not self.armed or not self.anchor_lat or not self.anchor_lon:
            return None
        return render_anchor_map_png(
            self.anchor_lat,
            self.anchor_lon,
            self.alarm_radius_m,
            self.track_points,
            self.current_lat,
            self.current_lon,
            current_heading=self.current_heading,
            current_sog=self.current_sog,
            current_soc=self.current_soc,
            current_wind_speed=self.current_wind_speed,
            current_wind_dir=self.current_wind_dir,
            current_depth=self.current_depth,
            wind_history=self.wind_history
        )

    def build_quick_menu(self):
        return {
            "inline_keyboard": [
                [
                    {"text": "⚓ Drop Anchor", "callback_data": "drop_current"},
                    {"text": "🔄 Reset to Heading", "callback_data": "reset_heading"}
                ],
                [
                    {"text": f"⛓️ +5m Rode ({self.rode_m:.0f}m)", "callback_data": "rode_plus"},
                    {"text": f"⛓️ -5m Rode ({self.rode_m:.0f}m)", "callback_data": "rode_minus"}
                ],
                [
                    {"text": f"⭕ +5m Radius ({self.alarm_radius_m:.0f}m)", "callback_data": "radius_plus"},
                    {"text": f"⭕ -5m Radius ({self.alarm_radius_m:.0f}m)", "callback_data": "radius_minus"}
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

        wind_str = f"{self.current_wind_speed:.1f} kn {wind_direction_cardinal(self.current_wind_dir)} ({self.current_wind_dir:.0f}°)" if (self.current_wind_speed is not None and self.current_wind_dir is not None) else "N/A"
        depth_str = f"{self.current_depth:.1f} m" if self.current_depth is not None else "N/A"

        msg = (
            f"⚓ <b>Anchor Watch Status</b>\n"
            f"━━━━━━━━━━━━━━━━━━━\n"
            f"• <b>Status:</b> {status_line}\n"
            f"• <b>Rode Length:</b> {self.rode_m:.0f} m\n"
            f"• <b>Alarm Radius:</b> {self.alarm_radius_m:.0f} m\n"
            f"• <b>True Wind:</b> {wind_str}\n"
            f"• <b>Water Depth:</b> {depth_str}\n"
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
            
        elif cmd in ("/status", "/anchor", "/map"):
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
                    png = self.render_map()
                    if png:
                        self.tg.send_photo(png, caption=msg, reply_markup=self.build_quick_menu(), chat_id=chat_id)
                        return
                else:
                    msg = f"❌ Failed to reset anchor: {res}"
                self.tg.send_message(msg, reply_markup=self.build_quick_menu(), chat_id=chat_id)
            elif len(parts) > 1 and parts[1].lower() == "off":
                self.disarm()
                self.tg.send_message("⚪ <b>Anchor Watch Disarmed.</b>", reply_markup=self.build_quick_menu(), chat_id=chat_id)
            else:
                png = self.render_map()
                msg = self.format_status_message()
                if png:
                    self.tg.send_photo(png, caption=msg, reply_markup=self.build_quick_menu(), chat_id=chat_id)
                else:
                    self.tg.send_message(msg, reply_markup=self.build_quick_menu(), chat_id=chat_id)

    def handle_callback_query(self, query):
        data = query.get("data", "")
        chat_id = query.get("message", {}).get("chat", {}).get("id")

        if data in ("drop_current", "drop_35"):
            self.poll_sensors()
            if self.current_lat and self.current_lon:
                self.arm_anchor_point(self.current_lat, self.current_lon, rode_m=self.rode_m)
                msg = f"⚓ <b>Anchor Dropped at Current GPS!</b>\n• Rode Length: <b>{self.rode_m:.0f} m</b>\n• Alarm Radius: <b>{self.alarm_radius_m:.0f} m</b>"
                png = self.render_map()
                if png:
                    self.tg.send_photo(png, caption=msg, reply_markup=self.build_quick_menu(), chat_id=chat_id)
                    return
            else:
                msg = "❌ GPS position not available."
            self.tg.send_message(msg, reply_markup=self.build_quick_menu(), chat_id=chat_id)

        elif data == "reset_heading":
            ok, res = self.reset_to_heading()
            if ok:
                lat, lon, d, r, hdg = res
                msg = f"🔄 <b>Anchor Reset to Heading {hdg:.0f}°!</b>\n• Chain Distance: <b>{d:.0f} m</b>\n• Alarm Radius: <b>{r:.0f} m</b>\n• Anchor GPS: <code>{lat:.5f}°, {lon:.5f}°</code>"
                png = self.render_map()
                if png:
                    self.tg.send_photo(png, caption=msg, reply_markup=self.build_quick_menu(), chat_id=chat_id)
                    return
            else:
                msg = f"❌ {res}"
            self.tg.send_message(msg, reply_markup=self.build_quick_menu(), chat_id=chat_id)

        elif data == "rode_plus":
            self.rode_m += 5.0
            self.alarm_radius_m = self.rode_m + self.config.get("default_safety_margin_m", 10.0)
            msg = f"⛓️ <b>Rode Distance Increased:</b>\n• Chain Rode: <b>{self.rode_m:.0f} m</b>\n• Alarm Radius: <b>{self.alarm_radius_m:.0f} m</b>"
            self.tg.send_message(msg, reply_markup=self.build_quick_menu(), chat_id=chat_id)

        elif data == "rode_minus":
            self.rode_m = max(5.0, self.rode_m - 5.0)
            self.alarm_radius_m = self.rode_m + self.config.get("default_safety_margin_m", 10.0)
            msg = f"⛓️ <b>Rode Distance Decreased:</b>\n• Chain Rode: <b>{self.rode_m:.0f} m</b>\n• Alarm Radius: <b>{self.alarm_radius_m:.0f} m</b>"
            self.tg.send_message(msg, reply_markup=self.build_quick_menu(), chat_id=chat_id)

        elif data == "radius_plus":
            self.alarm_radius_m += 5.0
            msg = f"⭕ <b>Alarm Radius Increased to {self.alarm_radius_m:.0f} m</b> (Rode: {self.rode_m:.0f} m)"
            self.tg.send_message(msg, reply_markup=self.build_quick_menu(), chat_id=chat_id)

        elif data == "radius_minus":
            self.alarm_radius_m = max(10.0, self.alarm_radius_m - 5.0)
            msg = f"⭕ <b>Alarm Radius Decreased to {self.alarm_radius_m:.0f} m</b> (Rode: {self.rode_m:.0f} m)"
            self.tg.send_message(msg, reply_markup=self.build_quick_menu(), chat_id=chat_id)

        elif data == "status":
            png = self.render_map()
            msg = self.format_status_message()
            if png:
                self.tg.send_photo(png, caption=msg, reply_markup=self.build_quick_menu(), chat_id=chat_id)
            else:
                self.tg.send_message(msg, reply_markup=self.build_quick_menu(), chat_id=chat_id)

        elif data == "toggle_deck":
            self.set_scheiber_switch(self.config.get("deck_light_channel", 3), 1)
            self.tg.send_message("💡 <b>Deck Floodlights Turned ON.</b>", reply_markup=self.build_quick_menu(), chat_id=chat_id)

        elif data == "deck_on":
            self.set_scheiber_switch(self.config.get("deck_light_channel", 3), 1)
            self.tg.send_message("💡 <b>Deck Floodlights ON.</b>", reply_markup=self.build_quick_menu(), chat_id=chat_id)

        elif data == "silence_15":
            self.silenced_until = time.monotonic() + 900.0
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
            
            if now - last_sensor_poll >= 2.0:
                service.poll_sensors()
                service.check_geofence()
                last_sensor_poll = now

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
