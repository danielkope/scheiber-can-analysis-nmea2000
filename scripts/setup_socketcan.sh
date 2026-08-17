#!/usr/bin/env bash
set -euo pipefail
IFACE="${1:-can1}"
BITRATE="${2:-250000}"
sudo ip link set "$IFACE" down 2>/dev/null || true
sudo ip link set "$IFACE" type can bitrate "$BITRATE" restart-ms 100
sudo ip link set "$IFACE" up
ip -details -statistics link show "$IFACE"
