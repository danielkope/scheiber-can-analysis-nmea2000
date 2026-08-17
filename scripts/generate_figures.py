#!/usr/bin/env python3
"""Generate reproducible engineering figures from analyzer CSV outputs."""
from __future__ import annotations

import argparse
import csv
from collections import defaultdict
from pathlib import Path
from typing import Iterable

import matplotlib.pyplot as plt


def read_rows(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def numeric_series(records: Iterable[dict[str, str]], suffix: str) -> dict[str, tuple[list[float], list[float]]]:
    temp: dict[str, list[tuple[float, float]]] = defaultdict(list)
    for row in records:
        name = row.get("name", "")
        if not name.endswith(suffix):
            continue
        try:
            temp[name].append((float(row["relative_seconds"]), float(row["value"])))
        except (KeyError, TypeError, ValueError):
            continue
    result: dict[str, tuple[list[float], list[float]]] = {}
    for name, points in temp.items():
        points.sort()
        result[name] = ([p[0] for p in points], [p[1] for p in points])
    return result


def save_lines(series: dict[str, tuple[list[float], list[float]]], title: str, ylabel: str, output: Path) -> None:
    fig, ax = plt.subplots(figsize=(10, 5.2))
    for name, (x, y) in sorted(series.items()):
        label = (name.replace("house_battery_candidate_", "House battery ")
                     .replace("charger_candidate_", "Charger ")
                     .replace("_candidate", "")
                     .replace("_", " "))
        ax.plot(x, y, linewidth=1.25, label=label)
    ax.set_title(title)
    ax.set_xlabel("Capture time (s)")
    ax.set_ylabel(ylabel)
    ax.grid(True, alpha=0.3)
    if series:
        ax.legend(fontsize=8, ncol=2)
    fig.tight_layout()
    fig.savefig(output, dpi=180)
    plt.close(fig)


def tank_plot(records: list[dict[str, str]], output: Path) -> None:
    wanted = {"water_level": "Water", "diesel_1_level": "Diesel 1", "diesel_2_level": "Diesel 2"}
    series: dict[str, tuple[list[float], list[float]]] = {}
    for key, label in wanted.items():
        pts: list[tuple[float, float]] = []
        for row in records:
            if row.get("name") != key:
                continue
            try:
                pts.append((float(row["relative_seconds"]), float(row["value"])))
            except (KeyError, TypeError, ValueError):
                pass
        pts.sort()
        series[label] = ([p[0] for p in pts], [p[1] for p in pts])
    save_lines(series, "Tank levels observed during capture", "Level (%)", output)


def id_count_plot(records: list[dict[str, str]], output: Path) -> None:
    pairs: list[tuple[str, int]] = []
    for row in records:
        try:
            pairs.append((row["can_id"], int(row["frame_count"])))
        except (KeyError, TypeError, ValueError):
            pass
    pairs.sort(key=lambda p: p[1], reverse=True)
    fig, ax = plt.subplots(figsize=(10, 7.2))
    labels = [p[0] for p in pairs]
    values = [p[1] for p in pairs]
    ax.barh(range(len(labels)), values)
    ax.set_yticks(range(len(labels)))
    ax.set_yticklabels(labels, fontsize=7)
    ax.invert_yaxis()
    ax.set_xlabel("Frame count")
    ax.set_title("CAN identifier activity in the 228.962 s capture")
    ax.grid(True, axis="x", alpha=0.3)
    fig.tight_layout()
    fig.savefig(output, dpi=180)
    plt.close(fig)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--derived", type=Path, default=Path("data/derived"))
    parser.add_argument("--output", type=Path, default=Path("docs/figures"))
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)

    tanks = read_rows(args.derived / "tank_samples.csv")
    batteries = read_rows(args.derived / "house_battery_candidates.csv")
    chargers = read_rows(args.derived / "charger_candidates.csv")
    inventory = read_rows(args.derived / "can_id_inventory.csv")

    tank_plot(tanks, args.output / "tank_levels.png")
    id_count_plot(inventory, args.output / "can_id_counts.png")
    save_lines(numeric_series(batteries, "_voltage"), "Six house-battery voltage candidates", "Voltage (V)", args.output / "house_battery_voltages.png")
    save_lines(numeric_series(batteries, "_current_code"), "Six house-battery signed current codes", "Raw signed code", args.output / "house_battery_current_codes.png")
    ac_series = numeric_series(chargers, "_ac_input_voltage_candidate")
    save_lines(ac_series, "Candidate AC input voltage by charger family", "AC voltage (V, candidate)", args.output / "charger_ac_input_voltage.png")
    save_lines(ac_series, "AC-source transition timeline", "AC voltage (V, candidate)", args.output / "ac_voltage_timeline.png")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
