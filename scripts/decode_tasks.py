#!/usr/bin/env python3
"""Decode RHCR KIVA task locations back to the original NodeID task format.

RHCR task rows use this format:

    agent_id pickup_location delivery_location [pickup_location delivery_location ...]

Each location is a row-major map cell id: ``row * width + column``. This
script maps those cells back to NodeIDs from the original nodes dictionary and
writes one original-style row per pickup/delivery pair:

    source destination availability pickup_wait dropoff_wait pickup_sequence dropoff_sequence task_sequence

The RHCR export does not retain the six trailing source-task columns. They are
therefore reconstructed from command-line defaults; task_sequence is generated
in output order unless overridden with --task-sequence-start.
"""

from __future__ import annotations

import argparse
import re
from pathlib import Path


def parse_nodes(path: Path) -> dict[tuple[int, int], int]:
    nodes: dict[tuple[int, int], int] = {}
    for line_no, raw_line in enumerate(path.read_text().splitlines(), start=1):
        line = raw_line.split("#", 1)[0].strip()
        if not line:
            continue
        parts = line.replace(",", " ").split()
        if len(parts) < 3:
            raise ValueError(f"{path}:{line_no}: expected NodeID GridX GridY")
        node_id, x, y = map(int, parts[:3])
        coordinate = (x, y)
        if coordinate in nodes:
            raise ValueError(f"{path}:{line_no}: duplicate node coordinate {coordinate}")
        nodes[coordinate] = node_id
    return nodes


def parse_map(path: Path) -> tuple[int, int, list[str]]:
    lines = path.read_text().splitlines()
    if not lines:
        raise ValueError(f"{path} is empty")

    first = lines[0].replace(" ", "")
    if "," in first:  # RHCR map: rows,cols followed by three metadata lines.
        rows, cols = map(int, first.split(",", 1))
        grid = lines[4 : 4 + rows]
    else:  # MovingAI map: type/height/width/map header.
        rows = cols = None
        map_start = None
        for index, line in enumerate(lines):
            parts = line.split()
            if len(parts) == 2 and parts[0].lower() == "height":
                rows = int(parts[1])
            elif len(parts) == 2 and parts[0].lower() == "width":
                cols = int(parts[1])
            elif len(parts) == 1 and parts[0].lower() == "map":
                map_start = index + 1
                break
        if rows is None or cols is None or map_start is None:
            raise ValueError(f"{path} is not a supported map format")
        grid = lines[map_start : map_start + rows]

    if len(grid) != rows or any(len(row) < cols for row in grid):
        raise ValueError(f"{path} has inconsistent map dimensions")
    return rows, cols, [row[:cols] for row in grid]


def parse_exported_tasks(path: Path) -> list[tuple[int, int]]:
    pairs: list[tuple[int, int]] = []
    for line_no, raw_line in enumerate(path.read_text().splitlines(), start=1):
        line = raw_line.split("#", 1)[0].strip()
        if not line:
            continue
        values = [int(value) for value in re.split(r"[\s,;:]+", line) if value]
        if len(values) < 3 or len(values) % 2 == 0:
            raise ValueError(
                f"{path}:{line_no}: expected agent_id pickup delivery [pickup delivery ...]"
            )
        for index in range(1, len(values), 2):
            pairs.append((values[index], values[index + 1]))
    return pairs


def location_to_node(
    location: int, rows: int, cols: int, grid: list[str], nodes: dict[tuple[int, int], int]
) -> int:
    if location < 0 or location >= rows * cols:
        raise ValueError(f"location {location} is outside the map")
    y, x = divmod(location, cols)
    if grid[y][x] == "@":
        raise ValueError(f"location {location} maps to obstacle cell ({x}, {y})")
    try:
        return nodes[(x, y)]
    except KeyError as exc:
        raise KeyError(f"location {location} maps to ({x}, {y}), absent from the nodes file") from exc


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tasks", type=Path, default=Path("maps/grid_map4.rhcr.tasks.txt"))
    parser.add_argument("--map", type=Path, default=Path("maps/grid_map4.map"))
    parser.add_argument("--nodes", type=Path, default=Path("maps/grid_map4.nodes.txt"))
    parser.add_argument("--output", type=Path, default=Path("maps/grid_map4.decoded.Tasks.txt"))
    parser.add_argument("--availability", type=int, default=0)
    parser.add_argument("--pickup-wait", type=int, default=0)
    parser.add_argument("--dropoff-wait", type=int, default=0)
    parser.add_argument("--pickup-sequence", type=int, default=0)
    parser.add_argument("--dropoff-sequence", type=int, default=0)
    parser.add_argument("--task-sequence-start", type=int, default=1)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    rows, cols, grid = parse_map(args.map)
    nodes = parse_nodes(args.nodes)
    pairs = parse_exported_tasks(args.tasks)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w") as output:
        for offset, (pickup, delivery) in enumerate(pairs):
            source = location_to_node(pickup, rows, cols, grid, nodes)
            destination = location_to_node(delivery, rows, cols, grid, nodes)
            task_sequence = args.task_sequence_start + offset
            output.write(
                f"{source} {destination} {args.availability} {args.pickup_wait} "
                f"{args.dropoff_wait} {args.pickup_sequence} {args.dropoff_sequence} "
                f"{task_sequence}\n"
            )
    print(f"Wrote {len(pairs)} decoded tasks to {args.output}")


if __name__ == "__main__":
    main()
