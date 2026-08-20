#!/usr/bin/env python3
"""Smart Anchor Watch & Multi-Sensor Alarm Service for Victron Cerbo GX.

Features:
  1. Geofence & Swing Circle Watch with Geodesic Bow Projection ("Reset to Heading").
  2. Persistent Anchor State on Disk (/data/conf/anchor_state.json) - survives restarts & reboots seamlessly.
  3. Dedicated Rotating File Logger (/data/scheiber-gx/anchor_watch.log, 2MB x 3 backups).
  4. Real-time NMEA 2000 listener (Wind PGN 130306, Depth PGN 128267, Heading PGN 127250, GPS PGN 129029).
  5. Multi-Sensor Alarms: Anchor Drag, Squall / High Wind, Wind Shift, Shallow Water, and Low Battery.
  6. Interactive Telegram Bot with real-time settings menu, per-alarm toggles, threshold adjustments, and baseline TWD reset.
  7. Pure-Cairo Vector Map Rendering with concentric rings, swing trail, live Wind Rose, and synchronized TWS/TWD multi-hour strip plot.
  8. Memory-leak proof with explicit Cairo surface disposal and history decimation.
  9. Physical lighting control via Scheiber switchboard (NEVER uses Cerbo Relay 1).
"""

import os
import sys
import time
import math
import json
import uuid
import io
import gc
import socket
import struct
import threading
import logging
import logging.handlers
import urllib.request
import urllib.parse
from datetime import datetime, timezone

try:
    import cairo
    HAVE_CAIRO = True
except ImportError:
    HAVE_CAIRO = False

# Logging Setup with Rotating File Handler
LOG_FILE = os.environ.get("ANCHOR_LOG", "/data/scheiber-gx/anchor_watch.log")
try:
    os.makedirs(os.path.dirname(LOG_FILE), exist_ok=True)
except Exception:
    pass

log = logging.getLogger("AnchorWatch")
log.setLevel(logging.INFO)
log_formatter = logging.Formatter("%(asctime)s [%(levelname)s] [AnchorWatch] %(message)s")

# Console handler
console_handler = logging.StreamHandler(sys.stdout)
console_handler.setFormatter(log_formatter)
if not log.handlers:
    log.addHandler(console_handler)

# Rotating file handler (2 MB max, 3 backups)
try:
    file_handler = logging.handlers.RotatingFileHandler(LOG_FILE, maxBytes=2 * 1024 * 1024, backupCount=3)
    file_handler.setFormatter(log_formatter)
    log.addHandler(file_handler)
except Exception as e:
    sys.stderr.write(f"Could not initialize file logger at {LOG_FILE}: {e}\n")

CONFIG_FILE = os.environ.get("ANCHOR_CONFIG", "/data/conf/anchor_watch_config.json")
STATE_FILE = os.environ.get("ANCHOR_STATE", "/data/conf/anchor_state.json")

DEFAULT_CONFIG = {
    "telegram_bot_token": "",
    "telegram_chat_id": "",
    "default_rode_m": 50.0,
    "default_safety_margin_m": 10.0,
    # Alarm Enable/Disable Toggles
    "alarm_drag_enabled": True,
    "alarm_squall_enabled": True,
    "alarm_wind_shift_enabled": True,
    "alarm_depth_enabled": True,
    "alarm_battery_enabled": True,
    # Alarm Thresholds
    "depth_alarm_threshold_m": 2.5,
    "wind_squall_gust_kn": 25.0,
    "wind_shift_threshold_deg": 60.0,
    "wind_shift_min_speed_kn": 3.0,
    "battery_low_soc_pct": 20.0,
    # Scheiber Lighting Integration
    "turn_on_deck_lights_on_alarm": True,
    "deck_light_channel": "deck_floodlight",  # Scheiber SwitchableOutput ID
    "cockpit_light_channel": "lighting"       # Scheiber SwitchableOutput ID
}

EARTH_RADIUS_M = 6371000.0
MAX_HISTORY_POINTS = 1000


def get_memory_rss_mb():
    """Read resident memory usage (RSS) in MB."""
    try:
        with open("/proc/self/status", "r") as f:
            for line in f:
                if line.startswith("VmRSS:"):
                    return float(line.split()[1]) / 1024.0
    except Exception:
        pass
    return None


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


def render_anchor_map_png(anchor_lat, anchor_lon, alarm_radius_m, track_points, current_lat, current_lon,
                          current_heading=0.0, current_sog=0.0, current_soc=None,
                          current_wind_speed=None, current_wind_dir=None, current_depth=None,
                          wind_history=None):
    """Render high-resolution dark nautical anchor watch map with synchronized TWS/TWD history plot."""
    if not HAVE_CAIRO:
        return None

    width, height = 900, 1020
    surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, width, height)
    ctx = cairo.Context(surface)

    # 1. Main Background
    ctx.set_source_rgb(0.04, 0.07, 0.12)
    ctx.paint()

    map_top = 105
    map_height = 560
    map_center_x = width / 2.0
    map_center_y = map_top + map_height / 2.0

    chart_top = 690
    chart_height = 270
    chart_left = 65
    chart_right = width - 65
    chart_width = chart_right - chart_left

    R = 6371000.0
    lat_rad = math.radians(anchor_lat) if anchor_lat else 0.0

    def gps_to_xy(lat, lon):
        d_lat = math.radians(lat - anchor_lat)
        d_lon = math.radians(lon - anchor_lon)
        north_m = d_lat * R
        east_m = d_lon * R * math.cos(lat_rad)
        return east_m, north_m

    all_x = [0.0]
    all_y = [0.0]
    for pt in (track_points or []):
        ex, ny = gps_to_xy(pt["lat"], pt["lon"])
        all_x.append(ex)
        all_y.append(ny)
    if current_lat and current_lon:
        cx, cy = gps_to_xy(current_lat, current_lon)
        all_x.append(cx)
        all_y.append(cy)

    max_dist = max(alarm_radius_m * 1.35, max(math.hypot(x, y) for x, y in zip(all_x, all_y)) * 1.25, 30.0)
    scale = (map_height / 2.0 - 45.0) / max_dist

    def to_pixel(east_m, north_m):
        return map_center_x + east_m * scale, map_center_y - north_m * scale

    # 2. TOP HUD HEADER
    ctx.set_source_rgba(0.02, 0.05, 0.09, 0.9)
    ctx.rectangle(15, 15, width - 30, 80)
    ctx.fill()
    ctx.set_source_rgba(0.2, 0.4, 0.6, 0.5)
    ctx.set_line_width(1.0)
    ctx.rectangle(15, 15, width - 30, 80)
    ctx.stroke()

    cur_dist = math.hypot(*gps_to_xy(current_lat, current_lon)) if (current_lat and current_lon) else 0.0
    ctx.select_font_face("Sans", cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_BOLD)
    ctx.set_font_size(16)
    ctx.set_source_rgb(0.2, 0.95, 0.65)
    ctx.move_to(30, 42)
    ctx.show_text(f"DISTANCE TO ANCHOR: {cur_dist:.1f} m  |  SAFE LIMIT: {alarm_radius_m:.0f} m")

    ctx.set_font_size(13)
    ctx.set_source_rgb(0.85, 0.92, 1.0)
    ctx.move_to(30, 66)
    soc_str = f"{current_soc:.0f}%" if current_soc is not None else "N/A"
    depth_str = f"{current_depth:.1f}m" if current_depth is not None else "N/A"
    card = wind_direction_cardinal(current_wind_dir)
    wind_str = f"{current_wind_speed:.1f}kn {card} ({current_wind_dir:.0f}°)" if (current_wind_speed is not None and current_wind_dir is not None) else "N/A"
    ctx.show_text(f"WIND: {wind_str}   DEPTH: {depth_str}   HDG: {current_heading:.0f}°   BATTERY: {soc_str}")

    ctx.set_font_size(11)
    ctx.set_source_rgba(0.5, 0.7, 0.9, 0.8)
    ctx.move_to(30, 85)
    ctx.show_text(f"SOG: {current_sog:.1f} kn   TRACK PTS: {len(track_points or [])}   WIND SAMPLES: {len(wind_history or [])}")

    # 3. ANCHOR MAP VIEWPORT
    ring_interval = 10.0 if max_dist <= 60 else (20.0 if max_dist <= 150 else 50.0)
    r = ring_interval
    while r <= max_dist:
        ctx.set_source_rgba(0.2, 0.35, 0.5, 0.25)
        ctx.set_line_width(1.0)
        ctx.arc(map_center_x, map_center_y, r * scale, 0, 2 * math.pi)
        ctx.stroke()

        ctx.select_font_face("Sans", cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_NORMAL)
        ctx.set_font_size(10)
        ctx.set_source_rgba(0.4, 0.6, 0.8, 0.6)
        ctx.move_to(map_center_x + 6, map_center_y - r * scale + 12)
        ctx.show_text(f"{r:.0f}m")
        r += ring_interval

    # Crosshairs
    ctx.set_source_rgba(0.2, 0.35, 0.5, 0.3)
    ctx.set_line_width(1.0)
    ctx.move_to(map_center_x, map_top + 10)
    ctx.line_to(map_center_x, map_top + map_height - 10)
    ctx.move_to(30, map_center_y)
    ctx.line_to(width - 30, map_center_y)
    ctx.stroke()

    # Safe Alarm Radius
    alarm_px = alarm_radius_m * scale
    ctx.set_source_rgba(0.1, 0.8, 0.4, 0.08)
    ctx.arc(map_center_x, map_center_y, alarm_px, 0, 2 * math.pi)
    ctx.fill()

    ctx.set_source_rgba(0.1, 0.9, 0.5, 0.85)
    ctx.set_line_width(2.0)
    ctx.set_dash([6.0, 4.0])
    ctx.arc(map_center_x, map_center_y, alarm_px, 0, 2 * math.pi)
    ctx.stroke()
    ctx.set_dash([])

    # Track History
    if track_points and len(track_points) > 1:
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

    # Rode Line
    if current_lat and current_lon:
        cx, cy = to_pixel(*gps_to_xy(current_lat, current_lon))
        ctx.set_source_rgba(1.0, 0.85, 0.2, 0.6)
        ctx.set_line_width(1.5)
        ctx.set_dash([4.0, 3.0])
        ctx.move_to(map_center_x, map_center_y)
        ctx.line_to(cx, cy)
        ctx.stroke()
        ctx.set_dash([])

    # Anchor Marker
    ctx.set_source_rgb(1.0, 0.3, 0.2)
    ctx.arc(map_center_x, map_center_y, 7.0, 0, 2 * math.pi)
    ctx.fill()
    ctx.set_source_rgb(1.0, 1.0, 1.0)
    ctx.set_line_width(2.0)
    ctx.arc(map_center_x, map_center_y, 7.0, 0, 2 * math.pi)
    ctx.stroke()

    ctx.select_font_face("Sans", cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_BOLD)
    ctx.set_font_size(12)
    ctx.set_source_rgb(1.0, 0.4, 0.3)
    ctx.move_to(map_center_x + 10, map_center_y + 16)
    ctx.show_text("⚓ ANCHOR")

    # Boat Hull
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

    # North-Up Compass Indicator
    nu_x = 55
    nu_y = map_top + 45
    ctx.set_source_rgba(0.02, 0.05, 0.09, 0.85)
    ctx.rectangle(nu_x - 30, nu_y - 38, 60, 76)
    ctx.fill()
    ctx.set_source_rgba(0.2, 0.4, 0.6, 0.5)
    ctx.set_line_width(1.0)
    ctx.rectangle(nu_x - 30, nu_y - 38, 60, 76)
    ctx.stroke()

    ctx.set_source_rgb(0.95, 0.25, 0.25)
    ctx.move_to(nu_x, nu_y - 25)
    ctx.line_to(nu_x - 6, nu_y - 4)
    ctx.line_to(nu_x + 6, nu_y - 4)
    ctx.close_path()
    ctx.fill()

    ctx.set_source_rgb(0.7, 0.8, 0.9)
    ctx.move_to(nu_x, nu_y + 18)
    ctx.line_to(nu_x - 6, nu_y - 4)
    ctx.line_to(nu_x + 6, nu_y - 4)
    ctx.close_path()
    ctx.fill()

    ctx.select_font_face("Sans", cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_BOLD)
    ctx.set_font_size(10)
    ctx.set_source_rgb(1.0, 1.0, 1.0)
    ctx.move_to(nu_x - 4, nu_y - 27)
    ctx.show_text("N")
    ctx.set_font_size(8)
    ctx.set_source_rgba(0.6, 0.8, 1.0, 0.9)
    ctx.move_to(nu_x - 22, nu_y + 30)
    ctx.show_text("NORTH UP")

    # Floating Wind Rose
    if current_wind_dir is not None:
        wr_x = width - 85
        wr_y = map_top + 45
        wr_rad = 36.0

        ctx.set_source_rgba(0.02, 0.05, 0.09, 0.85)
        ctx.rectangle(wr_x - 48, wr_y - 38, 96, 76)
        ctx.fill()
        ctx.set_source_rgba(0.2, 0.4, 0.6, 0.5)
        ctx.set_line_width(1.0)
        ctx.rectangle(wr_x - 48, wr_y - 38, 96, 76)
        ctx.stroke()

        ctx.select_font_face("Sans", cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_BOLD)
        ctx.set_font_size(9)
        ctx.set_source_rgba(0.0, 0.9, 1.0, 0.95)
        ctx.move_to(wr_x - 26, wr_y - 26)
        ctx.show_text("TRUE WIND")

        ctx.set_source_rgba(0.3, 0.5, 0.7, 0.4)
        ctx.set_line_width(1.0)
        ctx.arc(wr_x, wr_y + 3, wr_rad - 10, 0, 2 * math.pi)
        ctx.stroke()

        ctx.set_font_size(8)
        ctx.set_source_rgba(0.6, 0.8, 1.0, 0.9)
        ctx.move_to(wr_x - 3, wr_y + 3 - (wr_rad - 10) + 8)
        ctx.show_text("N")
        ctx.move_to(wr_x + (wr_rad - 10) - 8, wr_y + 6)
        ctx.show_text("E")
        ctx.move_to(wr_x - 3, wr_y + 3 + (wr_rad - 10) - 2)
        ctx.show_text("S")
        ctx.move_to(wr_x - (wr_rad - 10) + 2, wr_y + 6)
        ctx.show_text("W")

        w_rad = math.radians(current_wind_dir)
        w_center_y = wr_y + 3
        w_base_x = wr_x + (wr_rad - 8) * math.sin(w_rad)
        w_base_y = w_center_y - (wr_rad - 8) * math.cos(w_rad)
        w_tip_x = wr_x + 5.0 * math.sin(w_rad)
        w_tip_y = w_center_y - 5.0 * math.cos(w_rad)

        ctx.set_source_rgba(0.0, 0.95, 1.0, 0.95)
        ctx.set_line_width(2.5)
        ctx.move_to(w_base_x, w_base_y)
        ctx.line_to(w_tip_x, w_tip_y)
        ctx.stroke()

        vx = w_tip_x - w_base_x
        vy = w_tip_y - w_base_y
        L = math.hypot(vx, vy)
        if L > 0:
            ux, uy = vx / L, vy / L
            px, py = -uy, ux
            arr_len = 8.0
            arr_width = 4.5
            w1_x = w_tip_x - arr_len * ux + arr_width * px
            w1_y = w_tip_y - arr_len * uy + arr_width * py
            w2_x = w_tip_x - arr_len * ux - arr_width * px
            w2_y = w_tip_y - arr_len * uy - arr_width * py
            ctx.move_to(w_tip_x, w_tip_y)
            ctx.line_to(w1_x, w1_y)
            ctx.line_to(w2_x, w2_y)
            ctx.close_path()
            ctx.fill()

        ctx.set_font_size(9)
        ctx.set_source_rgb(1.0, 1.0, 1.0)
        spd_str = f"{current_wind_speed:.0f}kn" if current_wind_speed is not None else ""
        txt = f"FROM {card} ({spd_str})"
        ctx.move_to(wr_x - 30, wr_y + 32)
        ctx.show_text(txt)

    # 4. SYNCHRONIZED TWS & TWD TIME-SERIES PLOT
    ctx.set_source_rgba(0.02, 0.05, 0.09, 0.9)
    ctx.rectangle(15, chart_top - 15, width - 30, chart_height)
    ctx.fill()
    ctx.set_source_rgba(0.2, 0.4, 0.6, 0.5)
    ctx.set_line_width(1.0)
    ctx.rectangle(15, chart_top - 15, width - 30, chart_height)
    ctx.stroke()

    # Chart Header & Legend
    ctx.select_font_face("Sans", cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_BOLD)
    ctx.set_font_size(12)
    ctx.set_source_rgb(0.0, 0.9, 1.0)
    ctx.move_to(chart_left, chart_top + 5)
    ctx.show_text("— TRUE WIND SPEED (TWS kn)")
    
    ctx.set_source_rgb(1.0, 0.75, 0.2)
    ctx.move_to(chart_left + 225, chart_top + 5)
    ctx.show_text("--- TRUE WIND DIRECTION (TWD °)")

    # Compute stats if data exists
    if wind_history and len(wind_history) > 1:
        speeds = [pt.get("tws", 0.0) for pt in wind_history]
        max_speed = max(speeds)
        avg_speed = sum(speeds) / len(speeds)
        t_span_hours = (wind_history[-1]["time"] - wind_history[0]["time"]) / 3600.0
        
        ctx.select_font_face("Sans", cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_NORMAL)
        ctx.set_font_size(11)
        ctx.set_source_rgba(0.7, 0.85, 1.0, 0.9)
        stats_txt = f"GUST: {max_speed:.1f} kn  |  AVG: {avg_speed:.1f} kn  |  SPAN: {t_span_hours:.1f}h"
        ctx.move_to(chart_right - 260, chart_top + 5)
        ctx.show_text(stats_txt)

    plot_y = chart_top + 22
    plot_h = chart_height - 65
    plot_bottom = plot_y + plot_h

    max_tws = 20.0
    if wind_history:
        max_tws = max(max_tws, max(pt.get("tws", 0.0) for pt in wind_history) * 1.25)

    # Horizontal Grid Lines & Y-Axis Labels
    ctx.set_line_width(0.75)
    for i in range(5):
        ratio = i / 4.0
        gy = plot_bottom - ratio * plot_h
        ctx.set_source_rgba(0.2, 0.35, 0.5, 0.3)
        ctx.move_to(chart_left, gy)
        ctx.line_to(chart_right, gy)
        ctx.stroke()

        ctx.select_font_face("Sans", cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_NORMAL)
        ctx.set_font_size(10)
        ctx.set_source_rgb(0.0, 0.85, 0.95)
        ctx.move_to(chart_left - 32, gy + 4)
        ctx.show_text(f"{ratio * max_tws:.0f}k")

        deg_val = ratio * 360.0
        card_label = ["N", "E", "S", "W", "N"][i]
        ctx.set_source_rgb(1.0, 0.75, 0.2)
        ctx.move_to(chart_right + 8, gy + 4)
        ctx.show_text(f"{card_label} ({deg_val:.0f}°)")

    # Data Rendering & Dynamic Time Axis
    if wind_history and len(wind_history) > 1:
        t_min = wind_history[0]["time"]
        t_max = wind_history[-1]["time"]
        t_span = max(t_max - t_min, 60.0)

        # Determine adaptive time step
        if t_span <= 900: # <= 15m
            step = 180 # 3m
        elif t_span <= 3600: # <= 1h
            step = 600 # 10m
        elif t_span <= 3 * 3600: # <= 3h
            step = 1800 # 30m
        elif t_span <= 8 * 3600: # <= 8h
            step = 3600 # 1h
        elif t_span <= 16 * 3600: # <= 16h
            step = 7200 # 2h
        elif t_span <= 24 * 3600: # <= 24h
            step = 14400 # 4h
        else:
            step = 21600 # 6h

        # Vertical Time Grid Lines & Time Axis Ticks
        first_tick = math.ceil(t_min / step) * step
        cur_t = first_tick
        while cur_t <= t_max:
            tx = chart_left + ((cur_t - t_min) / t_span) * chart_width
            if chart_left + 15 <= tx <= chart_right - 15:
                # Vertical grid line
                ctx.set_source_rgba(0.2, 0.35, 0.5, 0.25)
                ctx.set_line_width(0.75)
                ctx.move_to(tx, plot_y)
                ctx.line_to(tx, plot_bottom)
                ctx.stroke()

                # Bottom tick
                ctx.set_source_rgba(0.5, 0.7, 0.9, 0.7)
                ctx.move_to(tx, plot_bottom)
                ctx.line_to(tx, plot_bottom + 4)
                ctx.stroke()

                # Time Label (Clock time + Relative)
                time_str = datetime.fromtimestamp(cur_t, timezone.utc).strftime("%H:%M")
                diff_m = int((t_max - cur_t) / 60)
                rel_str = "NOW" if diff_m < 2 else (f"-{diff_m//60}h" if diff_m % 60 == 0 else f"-{diff_m}m")
                
                ctx.select_font_face("Sans", cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_NORMAL)
                ctx.set_font_size(9)
                ctx.set_source_rgba(0.6, 0.8, 1.0, 0.85)
                ctx.move_to(tx - 14, plot_bottom + 16)
                ctx.show_text(time_str)

                ctx.set_font_size(8)
                ctx.set_source_rgba(0.4, 0.6, 0.8, 0.7)
                ctx.move_to(tx - 10, plot_bottom + 27)
                ctx.show_text(rel_str)

            cur_t += step

        # Baseline axis line
        ctx.set_source_rgba(0.3, 0.5, 0.7, 0.6)
        ctx.set_line_width(1.0)
        ctx.move_to(chart_left, plot_bottom)
        ctx.line_to(chart_right, plot_bottom)
        ctx.stroke()

        # 1. Fill Area for TWS
        first_x = chart_left + ((wind_history[0]["time"] - t_min) / t_span) * chart_width
        first_y = plot_bottom - (min(wind_history[0]["tws"], max_tws) / max_tws) * plot_h
        ctx.set_source_rgba(0.0, 0.8, 1.0, 0.15)
        ctx.move_to(first_x, plot_bottom)
        ctx.line_to(first_x, first_y)
        for pt in wind_history[1:]:
            px = chart_left + ((pt["time"] - t_min) / t_span) * chart_width
            py = plot_bottom - (min(pt["tws"], max_tws) / max_tws) * plot_h
            ctx.line_to(px, py)
        ctx.line_to(chart_left + chart_width, plot_bottom)
        ctx.close_path()
        ctx.fill()

        # 2. Solid Line for TWS
        ctx.set_source_rgba(0.0, 0.95, 1.0, 0.95)
        ctx.set_line_width(2.0)
        ctx.move_to(first_x, first_y)
        for pt in wind_history[1:]:
            px = chart_left + ((pt["time"] - t_min) / t_span) * chart_width
            py = plot_bottom - (min(pt["tws"], max_tws) / max_tws) * plot_h
            ctx.line_to(px, py)
        ctx.stroke()

        # 3. Dashed Amber Line for TWD (with wraparound protection)
        ctx.set_source_rgba(1.0, 0.75, 0.2, 0.85)
        ctx.set_line_width(1.5)
        ctx.set_dash([4.0, 3.0])
        first_twd_y = plot_bottom - (wind_history[0]["twd"] / 360.0) * plot_h
        ctx.move_to(first_x, first_twd_y)
        for i in range(1, len(wind_history)):
            prev_pt = wind_history[i - 1]
            cur_pt = wind_history[i]
            px = chart_left + ((cur_pt["time"] - t_min) / t_span) * chart_width
            py = plot_bottom - (cur_pt["twd"] / 360.0) * plot_h
            if abs(cur_pt["twd"] - prev_pt["twd"]) > 180.0:
                ctx.stroke()
                ctx.move_to(px, py)
            else:
                ctx.line_to(px, py)
        ctx.stroke()
        ctx.set_dash([])

        for pt in wind_history:
            px = chart_left + ((pt["time"] - t_min) / t_span) * chart_width
            py = plot_bottom - (pt["twd"] / 360.0) * plot_h
            ctx.set_source_rgba(1.0, 0.8, 0.3, 0.9)
            ctx.arc(px, py, 2.5, 0, 2 * math.pi)
            ctx.fill()
    else:
        ctx.select_font_face("Sans", cairo.FONT_SLANT_ITALIC, cairo.FONT_WEIGHT_NORMAL)
        ctx.set_font_size(12)
        ctx.set_source_rgba(0.5, 0.7, 0.9, 0.6)
        ctx.move_to(chart_left + 220, plot_y + plot_h / 2.0)
        ctx.show_text("Collecting real-time wind history (TWS & TWD)...")

    # 5. BOTTOM TIMESTAMP & FOOTER
    now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    ctx.select_font_face("Sans", cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_NORMAL)
    ctx.set_font_size(11)
    ctx.set_source_rgba(0.5, 0.6, 0.7, 0.8)
    ctx.move_to(25, height - 12)
    ctx.show_text(f"Cerbo GX Smart Anchor Watch • {now_str} • Lat: {current_lat or 0:.5f}°, Lon: {current_lon or 0:.5f}°")

    buf = io.BytesIO()
    surface.flush()
    surface.write_to_png(buf)
    png_bytes = buf.getvalue()
    
    # Explicit Cairo memory cleanup
    surface.finish()
    del ctx
    del surface
    gc.collect()
    
    return png_bytes


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
    def __init__(self, config_path=CONFIG_FILE, state_path=STATE_FILE, can_interface="can1"):
        self.config_path = config_path
        self.state_path = state_path
        self.can_interface = can_interface
        self.config = self.load_config()
        self.tg = TelegramClient(
            self.config.get("telegram_bot_token", ""),
            self.config.get("telegram_chat_id", "")
        )
        
        # Anchor State (Defaults)
        self.armed = False
        self.anchor_lat = None
        self.anchor_lon = None
        self.rode_m = self.config.get("default_rode_m", 50.0)
        self.alarm_radius_m = self.rode_m + self.config.get("default_safety_margin_m", 10.0)
        self.set_time = None
        self.last_alarm_time = -1000.0
        self.silenced_until = 0.0
        
        # Alarm Cooldowns & Baseline States
        self.baseline_wind_dir = None
        self.last_squall_alarm_time = -1000.0
        self.last_wind_shift_alarm_time = -1000.0
        self.last_depth_alarm_time = -1000.0
        self.last_battery_alarm_time = -1000.0

        # History Buffers (capped & downsampled at MAX_HISTORY_POINTS)
        self.track_points = []
        self.wind_history = []
        self.last_track_record_time = 0.0
        self.last_state_save_time = 0.0
        self.start_monotonic = time.monotonic()
        self.start_utc = datetime.now(timezone.utc)

        # Sensor readings
        self.current_lat = None
        self.current_lon = None
        self.current_sog = 0.0
        self.current_heading = 0.0
        self.current_depth = None
        self.current_wind_speed = None
        self.current_wind_dir = None
        self.current_soc = None
        self.gps_sats = 0
        self.gps_fix = 0

        # N2K Heartbeat & Loss Detection Watchdog
        self.last_n2k_frame_time = 0.0
        self.n2k_online = False
        self.n2k_lost_notified = False

        # Load persisted active anchor state (if any)
        self.load_state()

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

    def save_config(self):
        try:
            os.makedirs(os.path.dirname(self.config_path), exist_ok=True)
            tmp = self.config_path + ".tmp"
            with open(tmp, "w") as f:
                json.dump(self.config, f, indent=2)
            os.replace(tmp, self.config_path)
            log.info(f"Saved config to {self.config_path}")
        except Exception as e:
            log.error(f"Failed to save config: {e}")

    def load_state(self):
        """Restore active anchor watch state and history from disk."""
        if not os.path.isfile(self.state_path):
            return
        try:
            with open(self.state_path, "r") as f:
                st = json.load(f)
            if st.get("armed"):
                self.armed = True
                self.anchor_lat = st.get("anchor_lat")
                self.anchor_lon = st.get("anchor_lon")
                self.rode_m = float(st.get("rode_m", self.rode_m))
                self.alarm_radius_m = float(st.get("alarm_radius_m", self.alarm_radius_m))
                self.baseline_wind_dir = st.get("baseline_wind_dir")
                self.track_points = st.get("track_points", [])
                self.wind_history = st.get("wind_history", [])
                if st.get("set_time_iso"):
                    try:
                        self.set_time = datetime.fromisoformat(st["set_time_iso"].replace("Z", "+00:00"))
                    except Exception:
                        self.set_time = datetime.now(timezone.utc)
                log.info(
                    f"Restored active anchor watch from state file: Anchor ({self.anchor_lat:.5f}, {self.anchor_lon:.5f}), "
                    f"Rode {self.rode_m}m, Radius {self.alarm_radius_m}m, BaseWind {self.baseline_wind_dir}°, "
                    f"Points: {len(self.track_points)} track / {len(self.wind_history)} wind"
                )
        except Exception as e:
            log.error(f"Failed to load anchor state {self.state_path}: {e}")

    def save_state(self):
        """Persist active anchor watch state and history to disk atomically."""
        try:
            os.makedirs(os.path.dirname(self.state_path), exist_ok=True)
            st = {
                "armed": self.armed,
                "anchor_lat": self.anchor_lat,
                "anchor_lon": self.anchor_lon,
                "rode_m": self.rode_m,
                "alarm_radius_m": self.alarm_radius_m,
                "baseline_wind_dir": self.baseline_wind_dir,
                "set_time_iso": self.set_time.isoformat() if self.set_time else None,
                "track_points": self.track_points[-MAX_HISTORY_POINTS:],
                "wind_history": self.wind_history[-MAX_HISTORY_POINTS:],
                "updated_at": datetime.now(timezone.utc).isoformat()
            }
            tmp = self.state_path + ".tmp"
            with open(tmp, "w") as f:
                json.dump(st, f, indent=2)
            os.replace(tmp, self.state_path)
            self.last_state_save_time = time.monotonic()
        except Exception as e:
            log.error(f"Failed to save anchor state: {e}")

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
        while self.can_thread_running:
            s = None
            try:
                s = socket.socket(socket.AF_CAN, socket.SOCK_RAW, socket.CAN_RAW)
                s.bind((self.can_interface,))
                s.settimeout(2.0)
                log.info(f"N2K CAN listener active on {self.can_interface}")

                while self.can_thread_running:
                    try:
                        cf, addr = s.recvfrom(16)
                        now_m = time.monotonic()
                        self.last_n2k_frame_time = now_m
                        if not self.n2k_online:
                            self.n2k_online = True
                            if self.n2k_lost_notified:
                                self._notify_n2k_recovered()

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
                        log.debug(f"N2K frame read exception: {e}")
                        break
            except Exception as e:
                log.debug(f"Could not bind to {self.can_interface}: {e}")
            finally:
                if s:
                    try:
                        s.close()
                    except Exception:
                        pass

            if self.can_thread_running:
                time.sleep(3.0)

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
                            self.gps_sats = sats
                            self.gps_fix = int(fix)
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
        self.baseline_wind_dir = self.current_wind_dir
        self.track_points = []
        self.wind_history = []
        if self.current_lat and self.current_lon:
            self.track_points.append({"lat": self.current_lat, "lon": self.current_lon, "time": time.time()})
        if self.current_wind_speed is not None and self.current_wind_dir is not None:
            self.wind_history.append({"tws": self.current_wind_speed, "twd": self.current_wind_dir, "time": time.time()})
        
        self.save_state()
        log.info(f"Anchor Armed: Point ({self.anchor_lat:.5f}, {self.anchor_lon:.5f}), Rode: {self.rode_m}m, Radius: {self.alarm_radius_m}m, BaseWind: {self.baseline_wind_dir}°")

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
        self.save_state()
        log.info("Anchor Watch Disarmed.")

    def check_geofence(self):
        if not self.armed or self.current_lat is None or self.current_lon is None or self.anchor_lat is None:
            return

        now = time.monotonic()
        
        # Local snapshots to prevent race conditions with N2K listener thread
        cur_lat = self.current_lat
        cur_lon = self.current_lon
        cur_wind_spd = self.current_wind_speed
        cur_wind_dir = self.current_wind_dir
        cur_depth = self.current_depth
        cur_soc = self.current_soc
        base_wind_dir = self.baseline_wind_dir

        # Check NMEA 2000 communication watchdog (20 seconds without frames)
        if self.n2k_online or self.last_n2k_frame_time > 0:
            elapsed_n2k = now - self.last_n2k_frame_time
            if elapsed_n2k > 20.0 and self.n2k_online:
                self.n2k_online = False
                self.n2k_lost_notified = True
                self._notify_n2k_lost(elapsed_n2k)

        # 1. Record breadcrumbs & wind sample every 10s
        if now - self.last_track_record_time >= 10.0:
            record = True
            if self.track_points:
                last_pt = self.track_points[-1]
                d = haversine_distance_m(cur_lat, cur_lon, last_pt["lat"], last_pt["lon"])
                if d < 1.5 and (now - self.last_track_record_time < 60.0):
                    record = False
            if record:
                self.track_points.append({"lat": cur_lat, "lon": cur_lon, "time": time.time()})
                if cur_wind_spd is not None and cur_wind_dir is not None:
                    self.wind_history.append({"tws": cur_wind_spd, "twd": cur_wind_dir, "time": time.time()})
                    if self.baseline_wind_dir is None:
                        self.baseline_wind_dir = cur_wind_dir

                # Downsample history if exceeding MAX_HISTORY_POINTS to strictly bound memory
                if len(self.track_points) >= MAX_HISTORY_POINTS:
                    self.track_points = self.track_points[::2]
                if len(self.wind_history) >= MAX_HISTORY_POINTS:
                    self.wind_history = self.wind_history[::2]

                self.last_track_record_time = now

                # Periodic state persistence every 60s
                if now - self.last_state_save_time >= 60.0:
                    self.save_state()

        # 2. Anchor Drag Alarm (Geofence Breach)
        if self.config.get("alarm_drag_enabled", True):
            dist_m = haversine_distance_m(cur_lat, cur_lon, self.anchor_lat, self.anchor_lon)
            if dist_m > self.alarm_radius_m:
                if now > self.silenced_until and (now - self.last_alarm_time >= 30.0):
                    self.last_alarm_time = now
                    self.trigger_alarm(dist_m)

        # 3. Squall / High Wind Warning
        if self.config.get("alarm_squall_enabled", True):
            gust_thresh = float(self.config.get("wind_squall_gust_kn", 25.0))
            if cur_wind_spd is not None and cur_wind_spd >= gust_thresh:
                if now > self.silenced_until and (now - self.last_squall_alarm_time >= 600.0):
                    self.last_squall_alarm_time = now
                    self.trigger_squall_alarm(cur_wind_spd, cur_wind_dir, gust_thresh)

        # 4. Wind Shift Warning (only when wind speed >= min threshold to avoid light air false alarms)
        if self.config.get("alarm_wind_shift_enabled", True):
            min_wind_spd = float(self.config.get("wind_shift_min_speed_kn", 3.0))
            if cur_wind_spd is not None and cur_wind_spd >= min_wind_spd:
                shift_thresh = float(self.config.get("wind_shift_threshold_deg", 60.0))
                if base_wind_dir is not None and cur_wind_dir is not None:
                    shift_diff = abs((cur_wind_dir - base_wind_dir + 180.0) % 360.0 - 180.0)
                    if shift_diff >= shift_thresh:
                        if now > self.silenced_until and (now - self.last_wind_shift_alarm_time >= 900.0):
                            self.last_wind_shift_alarm_time = now
                            self.trigger_wind_shift_alarm(shift_diff, base_wind_dir, cur_wind_dir, shift_thresh)

        # 5. Shallow Water / Depth Drop Warning
        if self.config.get("alarm_depth_enabled", True):
            depth_thresh = float(self.config.get("depth_alarm_threshold_m", 2.5))
            if cur_depth is not None and cur_depth <= depth_thresh:
                if now > self.silenced_until and (now - self.last_depth_alarm_time >= 300.0):
                    self.last_depth_alarm_time = now
                    self.trigger_depth_alarm(cur_depth, depth_thresh)

        # 6. Low Battery Warning
        if self.config.get("alarm_battery_enabled", True):
            bat_thresh = float(self.config.get("battery_low_soc_pct", 20.0))
            if cur_soc is not None and cur_soc <= bat_thresh:
                if now > self.silenced_until and (now - self.last_battery_alarm_time >= 1800.0):
                    self.last_battery_alarm_time = now
                    self.trigger_battery_alarm(cur_soc, bat_thresh)

    def trigger_alarm(self, dist_m):
        log.warning(f"🚨 ANCHOR DRAG DETECTED: Distance {dist_m:.1f}m exceeds limit {self.alarm_radius_m:.1f}m!")
        
        if self.config.get("turn_on_deck_lights_on_alarm"):
            self.set_scheiber_switch(self.config.get("deck_light_channel", "deck_floodlight"), 1)
            self.set_scheiber_switch(self.config.get("cockpit_light_channel", "lighting"), 1)

        map_url = f"https://maps.google.com/?q={self.current_lat:.5f},{self.current_lon:.5f}"
        card = wind_direction_cardinal(self.current_wind_dir)
        msg = (
            f"🚨 <b>ANCHOR DRAG ALARM!</b>\n\n"
            f"⚠️ <b>Distance:</b> {dist_m:.1f} m (Limit: {self.alarm_radius_m:.1f} m)\n"
            f"💨 <b>Wind:</b> {self.current_wind_speed or 0:.1f} kn {card} ({self.current_wind_dir or 0:.0f}°)\n"
            f"🌊 <b>Depth:</b> {self.current_depth or 0:.1f} m\n"
            f"⚡ <b>SOG / Heading:</b> {self.current_sog:.1f} kn / {self.current_heading:.0f}°\n"
            f"📍 <b>Position:</b> <code>{self.current_lat:.5f}°, {self.current_lon:.5f}°</code>\n"
            f"🔋 <b>SoC:</b> {self.current_soc or 0:.0f}%\n\n"
            f"📍 <a href='{map_url}'><b>Open Live Position in Google Maps</b></a>\n"
            f"🔗 {map_url}"
        )
        markup = {
            "inline_keyboard": [
                [
                    {"text": "💡 Deck Lights ON", "callback_data": "deck_on"},
                    {"text": "🔄 Reset to Heading", "callback_data": "reset_heading"}
                ],
                [
                    {"text": "📍 Open Google Maps", "url": map_url},
                    {"text": "🔕 Silence 15m", "callback_data": "silence_15"}
                ],
                [
                    {"text": "❌ Disarm Watch", "callback_data": "disarm"}
                ]
            ]
        }

        png = self.render_map()
        if png:
            self.tg.send_photo(png, caption=msg, reply_markup=markup)
        else:
            self.tg.send_message(msg, reply_markup=markup)

    def trigger_squall_alarm(self, wind_speed, wind_dir, threshold):
        log.warning(f"💨 SQUALL WARNING: Wind speed {wind_speed:.1f} kn exceeds threshold {threshold:.1f} kn!")
        card = wind_direction_cardinal(wind_dir)
        map_url = f"https://maps.google.com/?q={self.current_lat or 0:.5f},{self.current_lon or 0:.5f}"
        msg = (
            f"💨 <b>SQUALL / HIGH WIND WARNING!</b>\n\n"
            f"⚠️ <b>Wind Speed:</b> <b>{wind_speed:.1f} kn</b> (Threshold: {threshold:.0f} kn)\n"
            f"🧭 <b>Direction:</b> FROM {card} ({wind_dir or 0:.0f}°)\n"
            f"🌊 <b>Depth:</b> {self.current_depth or 0:.1f} m\n"
            f"⚡ <b>SOG:</b> {self.current_sog:.1f} kn\n"
            f"🔋 <b>Battery:</b> {self.current_soc or 0:.0f}% SoC\n\n"
            f"📍 <a href='{map_url}'>Open Google Maps</a>"
        )
        png = self.render_map()
        if png:
            self.tg.send_photo(png, caption=msg, reply_markup=self.build_quick_menu())
        else:
            self.tg.send_message(msg, reply_markup=self.build_quick_menu())

    def trigger_wind_shift_alarm(self, shift_deg, base_dir, cur_dir, threshold):
        log.warning(f"🔄 WIND SHIFT WARNING: Wind shifted {shift_deg:.0f}° from {base_dir:.0f}° to {cur_dir:.0f}°!")
        base_card = wind_direction_cardinal(base_dir)
        cur_card = wind_direction_cardinal(cur_dir)
        map_url = f"https://maps.google.com/?q={self.current_lat or 0:.5f},{self.current_lon or 0:.5f}"
        msg = (
            f"🔄 <b>WIND SHIFT WARNING!</b>\n\n"
            f"⚠️ <b>Shift Angle:</b> <b>{shift_deg:.0f}°</b> (Threshold: {threshold:.0f}°)\n"
            f"🧭 <b>Origin:</b> Shifted from {base_card} ({base_dir:.0f}°) ➔ <b>{cur_card} ({cur_dir:.0f}°)</b>\n"
            f"💨 <b>Speed:</b> {self.current_wind_speed or 0:.1f} kn\n"
            f"🌊 <b>Depth:</b> {self.current_depth or 0:.1f} m\n\n"
            f"<i>Check lee shore proximity, swing clearance, and swell.</i>\n"
            f"📍 <a href='{map_url}'>Open Google Maps</a>"
        )
        png = self.render_map()
        if png:
            self.tg.send_photo(png, caption=msg, reply_markup=self.build_quick_menu())
        else:
            self.tg.send_message(msg, reply_markup=self.build_quick_menu())

    def trigger_depth_alarm(self, depth_m, threshold):
        log.warning(f"🌊 SHALLOW WATER ALARM: Depth {depth_m:.2f}m is below threshold {threshold:.1f}m!")
        map_url = f"https://maps.google.com/?q={self.current_lat or 0:.5f},{self.current_lon or 0:.5f}"
        msg = (
            f"🌊 <b>SHALLOW WATER WARNING!</b>\n\n"
            f"⚠️ <b>Water Depth:</b> <b>{depth_m:.2f} m</b> (Threshold: {threshold:.1f} m)\n"
            f"💨 <b>Wind:</b> {self.current_wind_speed or 0:.1f} kn\n"
            f"📍 <b>Position:</b> <code>{self.current_lat or 0:.5f}°, {self.current_lon or 0:.5f}°</code>\n\n"
            f"📍 <a href='{map_url}'>Open Google Maps</a>"
        )
        self.tg.send_message(msg, reply_markup=self.build_quick_menu())

    def trigger_battery_alarm(self, soc_pct, threshold):
        log.warning(f"🔋 LOW BATTERY WARNING: House battery SoC {soc_pct:.0f}% is below {threshold:.0f}%!")
        msg = (
            f"🔋 <b>LOW BATTERY WARNING!</b>\n\n"
            f"⚠️ <b>House Battery:</b> <b>{soc_pct:.0f}% SoC</b> (Threshold: {threshold:.0f}%)\n"
            f"💡 <i>Consider running engine/generator or reducing DC loads.</i>"
        )
        self.tg.send_message(msg, reply_markup=self.build_quick_menu())

    def _notify_n2k_lost(self, elapsed_s):
        log.warning(f"⚠️ NMEA 2000 communication lost! No frames received for {elapsed_s:.0f}s.")
        if self.armed and self.config.get("telegram_bot_token"):
            msg = (
                f"⚠️ <b>NMEA 2000 SIGNAL LOST!</b>\n\n"
                f"📡 No data received from <code>{self.can_interface}</code> for <b>{elapsed_s:.0f}s</b>.\n"
                f"💨 Wind & 🌊 Depth readings are temporarily paused.\n\n"
                f"🛡️ <i>Anchor Geofence Watch remains ACTIVE using D-Bus GPS.</i>"
            )
            self.tg.send_message(msg, reply_markup=self.build_quick_menu())

    def _notify_n2k_recovered(self):
        log.info("✅ NMEA 2000 communication restored.")
        self.n2k_lost_notified = False
        if self.armed and self.config.get("telegram_bot_token"):
            msg = (
                f"✅ <b>NMEA 2000 SIGNAL RESTORED!</b>\n\n"
                f"📡 Live data resumed on <code>{self.can_interface}</code>.\n"
                f"💨 Wind & 🌊 Depth sensors back online."
            )
            self.tg.send_message(msg, reply_markup=self.build_quick_menu())

    def get_scheiber_switch(self, channel=None):
        if not self.bus:
            return 0
        ch = channel or self.config.get("deck_light_channel", "deck_floodlight")
        if isinstance(ch, int) or (isinstance(ch, str) and ch.isdigit()):
            ch_map = {1: "electronics", 2: "deck_floodlight", 3: "deck_floodlight", 4: "lighting", 12: "lighting"}
            ch = ch_map.get(int(ch), "deck_floodlight")
        try:
            import dbus
            obj = self.bus.get_object("com.victronenergy.switch.scheiber", f"/SwitchableOutput/{ch}/State")
            val = obj.GetValue(dbus_interface="com.victronenergy.BusItem")
            return int(val) if val is not None else 0
        except Exception as e:
            log.debug(f"Failed to get Scheiber switch {ch}: {e}")
            return 0

    def set_scheiber_switch(self, channel, state):
        if not self.bus:
            return False
        ch = channel or self.config.get("deck_light_channel", "deck_floodlight")
        if isinstance(ch, int) or (isinstance(ch, str) and ch.isdigit()):
            ch_map = {1: "electronics", 2: "deck_floodlight", 3: "deck_floodlight", 4: "lighting", 12: "lighting"}
            ch = ch_map.get(int(ch), "deck_floodlight")
        try:
            import dbus
            obj = self.bus.get_object("com.victronenergy.switch.scheiber", f"/SwitchableOutput/{ch}/State")
            obj.SetValue(dbus.Int32(int(state)), dbus_interface="com.victronenergy.BusItem")
            log.info(f"Set Scheiber switch {ch} -> {state}")
            return True
        except Exception as e:
            log.error(f"Failed to set Scheiber switch {ch}: {e}")
            return False

    def toggle_scheiber_switch(self, channel=None):
        ch = channel or self.config.get("deck_light_channel", "deck_floodlight")
        cur = self.get_scheiber_switch(ch)
        new_state = 0 if cur == 1 else 1
        self.set_scheiber_switch(ch, new_state)
        return new_state

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
        deck_state = self.get_scheiber_switch(self.config.get("deck_light_channel", "deck_floodlight"))
        deck_btn_text = "💡 Deck Lights (ON)" if deck_state == 1 else "💡 Deck Lights (OFF)"
        map_url = f"https://maps.google.com/?q={self.current_lat or 0:.5f},{self.current_lon or 0:.5f}"
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
                    {"text": deck_btn_text, "callback_data": "toggle_deck"}
                ],
                [
                    {"text": "📍 Open in Google Maps", "url": map_url},
                    {"text": "⚙️ Alarm Settings", "callback_data": "settings_menu"}
                ],
                [
                    {"text": "❌ Disarm Alarm", "callback_data": "disarm"}
                ]
            ]
        }

    def build_settings_menu(self):
        drag_on = self.config.get("alarm_drag_enabled", True)
        squall_on = self.config.get("alarm_squall_enabled", True)
        shift_on = self.config.get("alarm_wind_shift_enabled", True)
        depth_on = self.config.get("alarm_depth_enabled", True)
        battery_on = self.config.get("alarm_battery_enabled", True)

        squall_val = float(self.config.get("wind_squall_gust_kn", 25.0))
        shift_val = float(self.config.get("wind_shift_threshold_deg", 60.0))
        depth_val = float(self.config.get("depth_alarm_threshold_m", 2.5))
        bat_val = float(self.config.get("battery_low_soc_pct", 20.0))

        base_twd = f"{self.baseline_wind_dir:.0f}°" if self.baseline_wind_dir is not None else "Not Set"
        cur_twd = f"{self.current_wind_dir:.0f}°" if self.current_wind_dir is not None else "N/A"

        return {
            "inline_keyboard": [
                [
                    {"text": f"🚨 Drag Alarm: {'🟢 ON' if drag_on else '⚪ OFF'}", "callback_data": "toggle_drag"}
                ],
                [
                    {"text": f"💨 Squall ({squall_val:.0f}kn): {'🟢' if squall_on else '⚪'}", "callback_data": "toggle_squall"},
                    {"text": "➖ 5kn", "callback_data": "squall_minus"},
                    {"text": "➕ 5kn", "callback_data": "squall_plus"}
                ],
                [
                    {"text": f"🔄 Shift (±{shift_val:.0f}°): {'🟢' if shift_on else '⚪'}", "callback_data": "toggle_shift"},
                    {"text": "➖ 15°", "callback_data": "shift_minus"},
                    {"text": "➕ 15°", "callback_data": "shift_plus"}
                ],
                [
                    {"text": f"🎯 Reset Baseline TWD (Base: {base_twd} | Cur: {cur_twd})", "callback_data": "reset_twd"}
                ],
                [
                    {"text": f"🌊 Depth ({depth_val:.1f}m): {'🟢' if depth_on else '⚪'}", "callback_data": "toggle_depth"},
                    {"text": "➖ 0.5m", "callback_data": "depth_minus"},
                    {"text": "➕ 0.5m", "callback_data": "depth_plus"}
                ],
                [
                    {"text": f"🔋 Battery ({bat_val:.0f}%): {'🟢' if battery_on else '⚪'}", "callback_data": "toggle_battery"},
                    {"text": "➖ 5%", "callback_data": "bat_minus"},
                    {"text": "➕ 5%", "callback_data": "bat_plus"}
                ],
                [
                    {"text": "⬅️ Back to Main Menu", "callback_data": "main_menu"}
                ]
            ]
        }

    def format_settings_message(self):
        drag_on = "🟢 ON" if self.config.get("alarm_drag_enabled", True) else "⚪ OFF"
        squall_on = "🟢 ON" if self.config.get("alarm_squall_enabled", True) else "⚪ OFF"
        shift_on = "🟢 ON" if self.config.get("alarm_wind_shift_enabled", True) else "⚪ OFF"
        depth_on = "🟢 ON" if self.config.get("alarm_depth_enabled", True) else "⚪ OFF"
        battery_on = "🟢 ON" if self.config.get("alarm_battery_enabled", True) else "⚪ OFF"

        squall_val = float(self.config.get("wind_squall_gust_kn", 25.0))
        shift_val = float(self.config.get("wind_shift_threshold_deg", 60.0))
        min_spd_val = float(self.config.get("wind_shift_min_speed_kn", 3.0))
        depth_val = float(self.config.get("depth_alarm_threshold_m", 2.5))
        bat_val = float(self.config.get("battery_low_soc_pct", 20.0))

        base_twd = f"{self.baseline_wind_dir:.0f}°" if self.baseline_wind_dir is not None else "Not Set"
        cur_twd = f"{self.current_wind_dir:.0f}°" if self.current_wind_dir is not None else "N/A"

        msg = (
            f"⚙️ <b>Smart Anchor Watch Settings</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"• 🚨 <b>Anchor Drag:</b> {drag_on} (Limit: {self.alarm_radius_m:.0f}m)\n"
            f"• 💨 <b>Squall Alarm:</b> {squall_on} (Limit: <b>{squall_val:.0f} kn</b>)\n"
            f"• 🔄 <b>Wind Shift:</b> {shift_on} (Sector: <b>±{shift_val:.0f}°</b> | Min Spd: <b>{min_spd_val:.0f} kn</b> | Baseline: <b>{base_twd}</b>)\n"
            f"• 🌊 <b>Shallow Water:</b> {depth_on} (Limit: <b>{depth_val:.1f} m</b>)\n"
            f"• 🔋 <b>Low Battery:</b> {battery_on} (Limit: <b>{bat_val:.0f}%</b>)\n\n"
            f"<i>Use the controls below to toggle alarms or adjust limits:</i>"
        )
        return msg

    def format_diagnostics_message(self):
        """Format detailed memory and service diagnostics message."""
        uptime_s = int(time.monotonic() - self.start_monotonic)
        uptime_h = uptime_s // 3600
        uptime_m = (uptime_s % 3600) // 60
        rss_mb = get_memory_rss_mb()
        rss_str = f"{rss_mb:.1f} MB" if rss_mb is not None else "N/A"

        if self.last_n2k_frame_time > 0:
            n2k_age = time.monotonic() - self.last_n2k_frame_time
            n2k_status = f"🟢 Online (last frame {n2k_age:.1f}s ago)" if n2k_age <= 20.0 else f"🔴 Signal Lost ({n2k_age:.0f}s ago)"
        else:
            n2k_status = "🟡 Waiting for frames"

        dbus_status = "🟢 Connected" if self.bus else "🟡 Disconnected"
        gps_status = f"🟢 Fix ({self.gps_sats} sats)" if self.current_lat else "🟡 Searching"

        return (
            f"🩺 <b>Anchor Watch Diagnostics</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"• ⏱️ <b>Service Uptime:</b> {uptime_h}h {uptime_m}m (Started: {self.start_utc.strftime('%H:%M:%S UTC')})\n"
            f"• 💾 <b>Process Memory (RSS):</b> <b>{rss_str}</b>\n"
            f"• 📍 <b>Track History:</b> {len(self.track_points)} / {MAX_HISTORY_POINTS} points\n"
            f"• 💨 <b>Wind History:</b> {len(self.wind_history)} / {MAX_HISTORY_POINTS} samples\n"
            f"• 📡 <b>N2K CAN Interface:</b> {n2k_status} ({self.can_interface})\n"
            f"• 🔌 <b>D-Bus SystemBus:</b> {dbus_status}\n"
            f"• 🛰️ <b>GPS State:</b> {gps_status}\n"
            f"• ⚓ <b>Watch State:</b> {'🟢 ARMED' if self.armed else '⚪ DISARMED'}\n"
            f"• 🗄️ <b>State File:</b> <code>{self.state_path}</code>\n"
            f"• 📜 <b>Log File:</b> <code>{LOG_FILE}</code>\n"
        )

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

        card = wind_direction_cardinal(self.current_wind_dir)
        wind_str = f"{self.current_wind_speed:.1f} kn {card} ({self.current_wind_dir:.0f}°)" if (self.current_wind_speed is not None and self.current_wind_dir is not None) else "N/A"
        depth_str = f"{self.current_depth:.1f} m" if self.current_depth is not None else "N/A"

        msg = (
            f"⚓ <b>Anchor Watch Status</b>\n"
            f"━━━━━━━━━━━━━━━━━━━\n"
            f"• <b>Status:</b> {status_line}\n"
            f"• <b>Rode Length:</b> {self.rode_m:.0f} m\n"
            f"• <b>Alarm Radius:</b> {self.alarm_radius_m:.0f} m\n"
            f"• <b>True Wind:</b> {wind_str}\n"
            f"• <b>Water Depth:</b> {depth_str}\n"
            f"• <b>Boat Position:</b> <code>{self.current_lat or 0:.5f}°, {self.current_lon or 0:.5f}°</code>\n"
            f"• <b>SOG / Heading:</b> {self.current_sog:.1f} kn / {self.current_heading:.0f}°\n"
            f"• <b>House Battery:</b> {self.current_soc or 0:.0f}% SoC\n\n"
            f"📍 <a href='{map_url}'><b>Open Live Position in Google Maps</b></a>\n"
            f"🔗 {map_url}"
        )
        return msg

    def handle_telegram_command(self, text, chat_id=None):
        parts = text.strip().split()
        cmd = parts[0].lower() if parts else ""
        
        if cmd in ("/start", "/help", "/menu"):
            msg = "⚓ <b>Cerbo GX Smart Anchor Watch</b>\nUse the quick buttons below or type /status:"
            self.tg.send_message(msg, reply_markup=self.build_quick_menu(), chat_id=chat_id)
            
        elif cmd in ("/settings", "/alarms", "/config"):
            self.tg.send_message(self.format_settings_message(), reply_markup=self.build_settings_menu(), chat_id=chat_id)

        elif cmd in ("/diag", "/health", "/mem", "/diagnostics"):
            self.tg.send_message(self.format_diagnostics_message(), reply_markup=self.build_quick_menu(), chat_id=chat_id)

        elif cmd in ("/status", "/anchor", "/map"):
            if len(parts) > 1 and parts[1].lower() == "reset":
                dist = float(parts[2]) if len(parts) > 2 and parts[2].isdigit() else self.rode_m
                rad = float(parts[3]) if len(parts) > 3 and parts[3].isdigit() else None
                ok, res = self.reset_to_heading(dist, rad)
                if ok:
                    lat, lon, d, r, hdg = res
                    map_url = f"https://maps.google.com/?q={self.current_lat or 0:.5f},{self.current_lon or 0:.5f}"
                    msg = (
                        f"🔄 <b>Anchor Point Reset to Heading!</b>\n\n"
                        f"• <b>Heading:</b> {hdg:.0f}°\n"
                        f"• <b>Chain Distance:</b> {d:.0f} m\n"
                        f"• <b>Alarm Radius:</b> {r:.0f} m\n"
                        f"• <b>New Anchor GPS:</b> <code>{lat:.5f}°, {lon:.5f}°</code>\n\n"
                        f"📍 <a href='{map_url}'>Open Google Maps</a>\n"
                        f"🔗 {map_url}"
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

        if data in ("drop_current", "drop_35", "set_anchor"):
            ok, res = self.reset_to_heading()
            if ok:
                lat, lon, d, r, hdg = res
                map_url = f"https://maps.google.com/?q={self.current_lat or 0:.5f},{self.current_lon or 0:.5f}"
                msg = (
                    f"⚓ <b>Anchor Dropped & Watch Armed!</b>\n\n"
                    f"• <b>Bow Heading:</b> {hdg:.0f}°\n"
                    f"• <b>Chain Rode:</b> {d:.0f} m ahead\n"
                    f"• <b>Safe Alarm Radius:</b> {r:.0f} m\n"
                    f"• <b>Anchor GPS:</b> <code>{lat:.5f}°, {lon:.5f}°</code>\n\n"
                    f"📍 <a href='{map_url}'><b>Open Live Position in Google Maps</b></a>\n"
                    f"🔗 {map_url}"
                )
                png = self.render_map()
                if png:
                    self.tg.send_photo(png, caption=msg, reply_markup=self.build_quick_menu(), chat_id=chat_id)
                    return
            else:
                msg = f"❌ Failed to set anchor: {res}"
            self.tg.send_message(msg, reply_markup=self.build_quick_menu(), chat_id=chat_id)

        elif data == "reset_heading":
            ok, res = self.reset_to_heading()
            if ok:
                lat, lon, d, r, hdg = res
                map_url = f"https://maps.google.com/?q={self.current_lat or 0:.5f},{self.current_lon or 0:.5f}"
                msg = (
                    f"🔄 <b>Anchor Point Re-centered!</b>\n\n"
                    f"• <b>Bow Heading:</b> {hdg:.0f}°\n"
                    f"• <b>Chain Rode:</b> {d:.0f} m ahead\n"
                    f"• <b>Safe Alarm Radius:</b> {r:.0f} m\n"
                    f"• <b>Anchor GPS:</b> <code>{lat:.5f}°, {lon:.5f}°</code>\n\n"
                    f"📍 <a href='{map_url}'><b>Open Live Position in Google Maps</b></a>\n"
                    f"🔗 {map_url}"
                )
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
            self.save_state()
            msg = f"⛓️ <b>Rode Distance Increased:</b>\n• Chain Rode: <b>{self.rode_m:.0f} m</b>\n• Alarm Radius: <b>{self.alarm_radius_m:.0f} m</b>"
            self.tg.send_message(msg, reply_markup=self.build_quick_menu(), chat_id=chat_id)

        elif data == "rode_minus":
            self.rode_m = max(5.0, self.rode_m - 5.0)
            self.alarm_radius_m = self.rode_m + self.config.get("default_safety_margin_m", 10.0)
            self.save_state()
            msg = f"⛓️ <b>Rode Distance Decreased:</b>\n• Chain Rode: <b>{self.rode_m:.0f} m</b>\n• Alarm Radius: <b>{self.alarm_radius_m:.0f} m</b>"
            self.tg.send_message(msg, reply_markup=self.build_quick_menu(), chat_id=chat_id)

        elif data == "radius_plus":
            self.alarm_radius_m += 5.0
            self.save_state()
            msg = f"⭕ <b>Alarm Radius Increased to {self.alarm_radius_m:.0f} m</b> (Rode: {self.rode_m:.0f} m)"
            self.tg.send_message(msg, reply_markup=self.build_quick_menu(), chat_id=chat_id)

        elif data == "radius_minus":
            self.alarm_radius_m = max(10.0, self.alarm_radius_m - 5.0)
            self.save_state()
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
            new_state = self.toggle_scheiber_switch(self.config.get("deck_light_channel", "deck_floodlight"))
            state_text = "Turned ON" if new_state == 1 else "Turned OFF"
            icon = "💡" if new_state == 1 else "🌑"
            self.tg.send_message(f"{icon} <b>Deck Floodlights {state_text}.</b>", reply_markup=self.build_quick_menu(), chat_id=chat_id)

        elif data == "deck_on":
            self.set_scheiber_switch(self.config.get("deck_light_channel", "deck_floodlight"), 1)
            self.tg.send_message("💡 <b>Deck Floodlights ON.</b>", reply_markup=self.build_quick_menu(), chat_id=chat_id)

        elif data == "silence_15":
            self.silenced_until = time.monotonic() + 900.0
            self.tg.send_message("🔕 <b>Alarm Silenced for 15 Minutes.</b>", reply_markup=self.build_quick_menu(), chat_id=chat_id)

        elif data == "disarm":
            self.disarm()
            self.tg.send_message("⚪ <b>Anchor Watch Disarmed.</b>", reply_markup=self.build_quick_menu(), chat_id=chat_id)

        # ----------------------------------------------------
        # SETTINGS MENU & PER-ALARM TOGGLE / ADJUSTMENT HANDLERS
        # ----------------------------------------------------
        elif data in ("settings_menu", "settings"):
            self.tg.send_message(self.format_settings_message(), reply_markup=self.build_settings_menu(), chat_id=chat_id)

        elif data == "main_menu":
            self.tg.send_message("⚓ <b>Main Menu:</b>", reply_markup=self.build_quick_menu(), chat_id=chat_id)

        elif data == "toggle_drag":
            self.config["alarm_drag_enabled"] = not self.config.get("alarm_drag_enabled", True)
            self.save_config()
            self.tg.send_message(self.format_settings_message(), reply_markup=self.build_settings_menu(), chat_id=chat_id)

        elif data == "toggle_squall":
            self.config["alarm_squall_enabled"] = not self.config.get("alarm_squall_enabled", True)
            self.save_config()
            self.tg.send_message(self.format_settings_message(), reply_markup=self.build_settings_menu(), chat_id=chat_id)

        elif data == "squall_plus":
            self.config["wind_squall_gust_kn"] = min(60.0, float(self.config.get("wind_squall_gust_kn", 25.0)) + 5.0)
            self.save_config()
            self.tg.send_message(self.format_settings_message(), reply_markup=self.build_settings_menu(), chat_id=chat_id)

        elif data == "squall_minus":
            self.config["wind_squall_gust_kn"] = max(10.0, float(self.config.get("wind_squall_gust_kn", 25.0)) - 5.0)
            self.save_config()
            self.tg.send_message(self.format_settings_message(), reply_markup=self.build_settings_menu(), chat_id=chat_id)

        elif data == "toggle_shift":
            self.config["alarm_wind_shift_enabled"] = not self.config.get("alarm_wind_shift_enabled", True)
            self.save_config()
            self.tg.send_message(self.format_settings_message(), reply_markup=self.build_settings_menu(), chat_id=chat_id)

        elif data == "shift_plus":
            self.config["wind_shift_threshold_deg"] = min(180.0, float(self.config.get("wind_shift_threshold_deg", 60.0)) + 15.0)
            self.save_config()
            self.tg.send_message(self.format_settings_message(), reply_markup=self.build_settings_menu(), chat_id=chat_id)

        elif data == "shift_minus":
            self.config["wind_shift_threshold_deg"] = max(15.0, float(self.config.get("wind_shift_threshold_deg", 60.0)) - 15.0)
            self.save_config()
            self.tg.send_message(self.format_settings_message(), reply_markup=self.build_settings_menu(), chat_id=chat_id)

        elif data == "reset_twd":
            self.poll_sensors()
            if self.current_wind_dir is not None:
                self.baseline_wind_dir = self.current_wind_dir
                self.save_state()
                card = wind_direction_cardinal(self.baseline_wind_dir)
                msg = f"🎯 <b>Baseline Wind Direction Reset to Current:</b>\n• Baseline TWD: <b>{self.baseline_wind_dir:.0f}° {card}</b>\n• Alert Sector: <b>±{self.config.get('wind_shift_threshold_deg', 60):.0f}°</b>"
            else:
                msg = "⚠️ Current wind direction is not available to set baseline."
            self.tg.send_message(msg, reply_markup=self.build_settings_menu(), chat_id=chat_id)

        elif data == "toggle_depth":
            self.config["alarm_depth_enabled"] = not self.config.get("alarm_depth_enabled", True)
            self.save_config()
            self.tg.send_message(self.format_settings_message(), reply_markup=self.build_settings_menu(), chat_id=chat_id)

        elif data == "depth_plus":
            self.config["depth_alarm_threshold_m"] = min(15.0, float(self.config.get("depth_alarm_threshold_m", 2.5)) + 0.5)
            self.save_config()
            self.tg.send_message(self.format_settings_message(), reply_markup=self.build_settings_menu(), chat_id=chat_id)

        elif data == "depth_minus":
            self.config["depth_alarm_threshold_m"] = max(0.5, float(self.config.get("depth_alarm_threshold_m", 2.5)) - 0.5)
            self.save_config()
            self.tg.send_message(self.format_settings_message(), reply_markup=self.build_settings_menu(), chat_id=chat_id)

        elif data == "toggle_battery":
            self.config["alarm_battery_enabled"] = not self.config.get("alarm_battery_enabled", True)
            self.save_config()
            self.tg.send_message(self.format_settings_message(), reply_markup=self.build_settings_menu(), chat_id=chat_id)

        elif data == "bat_plus":
            self.config["battery_low_soc_pct"] = min(60.0, float(self.config.get("battery_low_soc_pct", 20.0)) + 5.0)
            self.save_config()
            self.tg.send_message(self.format_settings_message(), reply_markup=self.build_settings_menu(), chat_id=chat_id)

        elif data == "bat_minus":
            self.config["battery_low_soc_pct"] = max(5.0, float(self.config.get("battery_low_soc_pct", 20.0)) - 5.0)
            self.save_config()
            self.tg.send_message(self.format_settings_message(), reply_markup=self.build_settings_menu(), chat_id=chat_id)


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
            log.error(f"Main loop exception: {e}", exc_info=True)
            time.sleep(2.0)


if __name__ == "__main__":
    main()
