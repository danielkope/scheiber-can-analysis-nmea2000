import pytest
import math
import sys
import os

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "cerbo")))
import anchor_watch_service as aws


def test_haversine_distance_zero():
    dist = aws.haversine_distance_m(43.5000, 16.2000, 43.5000, 16.2000)
    assert dist == pytest.approx(0.0, abs=1e-3)


def test_haversine_distance_known():
    # 1 nautical mile (1852m) is approx 1 arcminute of latitude
    lat1, lon1 = 43.0000, 16.0000
    lat2, lon2 = 43.0166667, 16.0000
    dist = aws.haversine_distance_m(lat1, lon1, lat2, lon2)
    assert dist == pytest.approx(1853.2, abs=5.0)


def test_project_anchor_point_north():
    # Project 100m due North (0 deg)
    lat1, lon1 = 43.5000, 16.2000
    lat2, lon2 = aws.project_anchor_point(lat1, lon1, 0.0, 100.0)
    assert lat2 > lat1
    assert lon2 == pytest.approx(lon1, abs=1e-5)
    dist = aws.haversine_distance_m(lat1, lon1, lat2, lon2)
    assert dist == pytest.approx(100.0, abs=0.5)


def test_project_anchor_point_east():
    # Project 100m due East (90 deg)
    lat1, lon1 = 43.5000, 16.2000
    lat2, lon2 = aws.project_anchor_point(lat1, lon1, 90.0, 100.0)
    assert lat2 == pytest.approx(lat1, abs=1e-5)
    assert lon2 > lon1
    dist = aws.haversine_distance_m(lat1, lon1, lat2, lon2)
    assert dist == pytest.approx(100.0, abs=0.5)


def test_bearing_to_target():
    lat1, lon1 = 43.5000, 16.2000
    lat2, lon2 = aws.project_anchor_point(lat1, lon1, 45.0, 100.0)
    bearing = aws.bearing_to_target(lat1, lon1, lat2, lon2)
    assert bearing == pytest.approx(45.0, abs=0.5)


def test_anchor_service_arming_and_reset():
    svc = aws.AnchorWatchService(config_path="/tmp/nonexistent_config.json")
    svc.current_lat = 43.5000
    svc.current_lon = 16.2000
    svc.current_heading = 180.0 # South
    
    # 1. Arm anchor directly
    svc.arm_anchor_point(43.5000, 16.2000, rode_m=40.0, radius_m=50.0)
    assert svc.armed is True
    assert svc.rode_m == 40.0
    assert svc.alarm_radius_m == 50.0

    # 2. Reset to heading
    ok, res = svc.reset_to_heading(distance_m=45.0, radius_m=55.0)
    assert ok is True
    lat, lon, dist, rad, hdg = res
    assert lat < 43.5000  # Projected South
    assert dist == 45.0
    assert rad == 55.0
    assert hdg == 180.0


def test_anchor_service_geofence_alarm_logic():
    svc = aws.AnchorWatchService(config_path="/tmp/nonexistent_config.json")
    svc.current_lat = 43.5000
    svc.current_lon = 16.2000
    svc.arm_anchor_point(43.5000, 16.2000, rode_m=30.0, radius_m=40.0)

    alarms = []
    svc.trigger_alarm = lambda d: alarms.append(d)

    # Inside safe radius (10m away)
    new_lat, new_lon = aws.project_anchor_point(43.5000, 16.2000, 0.0, 10.0)
    svc.current_lat = new_lat
    svc.current_lon = new_lon
    svc.check_geofence()
    assert len(alarms) == 0

    # Outside radius (50m away)
    new_lat, new_lon = aws.project_anchor_point(43.5000, 16.2000, 0.0, 50.0)
    svc.current_lat = new_lat
    svc.current_lon = new_lon
    svc.check_geofence()
    assert len(alarms) == 1
    assert alarms[0] == pytest.approx(50.0, abs=0.5)


def test_quick_menu_structure():
    svc = aws.AnchorWatchService(config_path="/tmp/nonexistent_config.json")
    menu = svc.build_quick_menu()
    assert "inline_keyboard" in menu
    buttons = [btn["text"] for row in menu["inline_keyboard"] for btn in row]
    assert any("Drop" in b for b in buttons)
    assert any("Reset" in b for b in buttons)
    assert any("Rode" in b for b in buttons)
    assert any("Radius" in b for b in buttons)
    assert any("Status" in b for b in buttons)
    assert any("Disarm" in b for b in buttons)


def test_rode_and_radius_adjustments():
    svc = aws.AnchorWatchService(config_path="/tmp/nonexistent_config.json")
    svc.rode_m = 35.0
    svc.alarm_radius_m = 45.0

    # Increase rode
    svc.handle_callback_query({"data": "rode_plus", "message": {"chat": {"id": 12345}}})
    assert svc.rode_m == 40.0
    assert svc.alarm_radius_m == 50.0

    # Decrease rode
    svc.handle_callback_query({"data": "rode_minus", "message": {"chat": {"id": 12345}}})
    assert svc.rode_m == 35.0
    assert svc.alarm_radius_m == 45.0

    # Increase radius independently
    svc.handle_callback_query({"data": "radius_plus", "message": {"chat": {"id": 12345}}})
    assert svc.alarm_radius_m == 50.0

    # Decrease radius
    svc.handle_callback_query({"data": "radius_minus", "message": {"chat": {"id": 12345}}})
    assert svc.alarm_radius_m == 45.0


def test_drop_current_projects_ahead():
    svc = aws.AnchorWatchService(config_path="/tmp/nonexistent_config.json")
    svc.current_lat = 43.5000
    svc.current_lon = 16.2000
    svc.current_heading = 0.0 # North
    svc.rode_m = 50.0

    # Tapping Drop Anchor should project anchor 50m North
    svc.handle_callback_query({"data": "drop_current", "message": {"chat": {"id": 12345}}})
    assert svc.armed is True
    assert svc.anchor_lat > 43.5000 # North of boat
    dist = aws.haversine_distance_m(43.5000, 16.2000, svc.anchor_lat, svc.anchor_lon)
    assert dist == pytest.approx(50.0, abs=0.5)


def test_squall_alarm_trigger():
    svc = aws.AnchorWatchService(config_path="/tmp/nonexistent_config.json")
    svc.arm_anchor_point(43.5000, 16.2000, rode_m=50.0, radius_m=60.0)
    svc.current_lat = 43.5000
    svc.current_lon = 16.2000

    squall_events = []
    svc.trigger_squall_alarm = lambda spd, d, th: squall_events.append((spd, d, th))

    # Wind below threshold (18 kn)
    svc.current_wind_speed = 18.0
    svc.current_wind_dir = 280.0
    svc.check_geofence()
    assert len(squall_events) == 0

    # Squall gust (28 kn)
    svc.current_wind_speed = 28.0
    svc.check_geofence()
    assert len(squall_events) == 1
    assert squall_events[0][0] == 28.0


def test_wind_shift_alarm_trigger():
    svc = aws.AnchorWatchService(config_path="/tmp/nonexistent_config.json")
    svc.current_wind_dir = 200.0
    svc.arm_anchor_point(43.5000, 16.2000, rode_m=50.0, radius_m=60.0)
    svc.current_lat = 43.5000
    svc.current_lon = 16.2000

    shift_events = []
    svc.trigger_wind_shift_alarm = lambda diff, b, c, th: shift_events.append((diff, b, c, th))

    # Small shift (+20 deg)
    svc.current_wind_dir = 220.0
    svc.check_geofence()
    assert len(shift_events) == 0

    # Major shift (+70 deg from 200 to 270)
    svc.current_wind_dir = 270.0
    svc.check_geofence()
    assert len(shift_events) == 1
    assert shift_events[0][0] == pytest.approx(70.0)


def test_depth_alarm_trigger():
    svc = aws.AnchorWatchService(config_path="/tmp/nonexistent_config.json")
    svc.arm_anchor_point(43.5000, 16.2000, rode_m=50.0, radius_m=60.0)
    svc.current_lat = 43.5000
    svc.current_lon = 16.2000

    depth_events = []
    svc.trigger_depth_alarm = lambda d, th: depth_events.append((d, th))

    # Safe depth (6.0m)
    svc.current_depth = 6.0
    svc.check_geofence()
    assert len(depth_events) == 0

    # Shallow depth (2.1m)
    svc.current_depth = 2.1
    svc.check_geofence()
    assert len(depth_events) == 1
    assert depth_events[0][0] == 2.1
