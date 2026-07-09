#!/usr/bin/env python3
"""Convert external task rows to RHCR KIVA task assignment format.

Input task rows are expected to have at least two columns:

    source destination availability pickup_wait dropoff_wait ...

Only the first two columns are used. They are interpreted as NodeID values from
the nodes file, then converted to RHCR map location ids: row * width + col.

The output format is the one consumed by KivaSystem::load_task_assignments():

    agent_id pickup delivery [pickup delivery ...]

By default, each external task becomes one unassigned RHCR task line beginning
with agent id 0. RHCR then hands these task sequences to agents as they become
available.
"""

from __future__ import annotations

import argparse
import re
from pathlib import Path


def parse_nodes(path: Path) -> dict[int, tuple[int, int]]:
    nodes: dict[int, tuple[int, int]] = {}
    for line_no, raw_line in enumerate(path.read_text().splitlines(), start=1):
        line = raw_line.split("#", 1)[0].strip()
        if not line:
            continue
        parts = line.replace(",", " ").split()
        if len(parts) < 3:
            raise ValueError(f"{path}:{line_no}: expected at least 3 columns")
        node_id, grid_x, grid_y = map(int, parts[:3])
        nodes[node_id] = (grid_x, grid_y)
    return nodes


def parse_movingai_map(path: Path) -> tuple[int, int, list[str]]:
    lines = path.read_text().splitlines()
    height = width = None
    map_start = None
    for i, line in enumerate(lines):
        parts = line.split()
        if len(parts) == 2 and parts[0] == "height":
            height = int(parts[1])
        elif len(parts) == 2 and parts[0] == "width":
            width = int(parts[1])
        elif parts == ["map"]:
            map_start = i + 1
            break
    if height is None or width is None or map_start is None:
        raise ValueError(f"{path} does not look like a MovingAI .map file")
    grid = lines[map_start : map_start + height]
    if len(grid) != height or any(len(row) < width for row in grid):
        raise ValueError(f"{path} has inconsistent map dimensions")
    return height, width, [row[:width] for row in grid]


def infer_width(nodes: dict[int, tuple[int, int]]) -> int:
    max_x = max(x for x, _ in nodes.values())
    return max_x + 1


def parse_task_pairs(path: Path) -> list[tuple[int, int]]:
    pairs: list[tuple[int, int]] = []
    for line_no, raw_line in enumerate(path.read_text().splitlines(), start=1):
        line = raw_line.split("#", 1)[0].strip()
        if not line:
            continue
        parts = re.split(r"[\s,;:]+", line)
        if len(parts) < 2:
            raise ValueError(f"{path}:{line_no}: expected source and destination")
        try:
            source = int(parts[0])
            destination = int(parts[1])
        except ValueError as exc:
            raise ValueError(f"{path}:{line_no}: source/destination must be integers") from exc
        pairs.append((source, destination))
    return pairs


def node_to_location(
    node_id: int,
    nodes: dict[int, tuple[int, int]],
    width: int,
    grid: list[str] | None,
) -> int:
    if node_id not in nodes:
        raise KeyError(f"node id {node_id} is not present in the nodes file")
    x, y = nodes[node_id]
    if grid is not None:
        height = len(grid)
        if not (0 <= y < height and 0 <= x < width):
            raise ValueError(f"node {node_id} has out-of-map position ({x}, {y})")
        if grid[y][x] == "@":
            raise ValueError(f"node {node_id} maps to obstacle cell ({x}, {y})")
    return y * width + x


def convert(args: argparse.Namespace) -> None:
    nodes = parse_nodes(args.nodes)
    grid = None
    width = args.width
    if args.map is not None:
        _, width, grid = parse_movingai_map(args.map)
    elif width is None:
        width = infer_width(nodes)

    task_pairs = parse_task_pairs(args.tasks)
    converted = [
        (
            node_to_location(source, nodes, width, grid),
            node_to_location(destination, nodes, width, grid),
        )
        for source, destination in task_pairs
    ]

    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w") as f:
        if args.single_sequence:
            fields = [str(args.agent_id)]
            for pickup, delivery in converted:
                fields.extend([str(pickup), str(delivery)])
            f.write(" ".join(fields) + "\n")
        else:
            for pickup, delivery in converted:
                f.write(f"{args.agent_id} {pickup} {delivery}\n")

    print(f"Wrote {len(converted)} tasks to {args.output}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tasks", type=Path, default=Path("maps/Tasks.txt"))
    parser.add_argument("--nodes", type=Path, default=Path("maps/grid_map4.nodes.txt"))
    parser.add_argument("--map", type=Path, default=Path("maps/grid_map4.map"))
    parser.add_argument("--output", type=Path, default=Path("maps/grid_map4.rhcr.tasks.txt"))
    parser.add_argument("--agent-id", type=int, default=0)
    parser.add_argument("--width", type=int, help="Map width if --map is omitted")
    parser.add_argument(
        "--single-sequence",
        action="store_true",
        help="Write all pickup/dropoff pairs on one line instead of one task per line",
    )
    return parser.parse_args()


if __name__ == "__main__":
    convert(parse_args())
