#!/usr/bin/env python3
"""Convert a MovingAI-style .map file to RHCR's custom unweighted .map format.

RHCR's KivaGrid::load_unweighted_map() expects:

    rows,cols
    number_of_endpoints
    number_of_agents_or_homes
    max_time
    <rows of map characters>

The map body can use:
    @ = obstacle
    e = endpoint
    r = robot home
    anything else = travel cell
"""

from __future__ import annotations

import argparse
from pathlib import Path


def read_movingai_map(path: Path) -> tuple[int, int, list[str]]:
    lines = path.read_text().splitlines()
    height = width = None
    map_start = None

    for i, line in enumerate(lines):
        parts = line.split()
        if len(parts) == 2 and parts[0].lower() == "height":
            height = int(parts[1])
        elif len(parts) == 2 and parts[0].lower() == "width":
            width = int(parts[1])
        elif len(parts) == 1 and parts[0].lower() == "map":
            map_start = i + 1
            break

    if height is None or width is None or map_start is None:
        raise ValueError(f"{path} does not look like a MovingAI .map file")

    grid = lines[map_start : map_start + height]
    if len(grid) != height:
        raise ValueError(f"{path}: expected {height} map rows, found {len(grid)}")

    normalized = []
    for row_id, row in enumerate(grid, start=1):
        if len(row) < width:
            raise ValueError(f"{path}: row {row_id} is shorter than width {width}")
        normalized.append(row[:width])

    return height, width, normalized


def convert_cell(ch: str) -> str:
    if ch == "@":
        return "@"
    if ch in {"e", "E"}:
        return "e"
    if ch in {"r", "R"}:
        return "r"
    return "."


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


def apply_home_cells(
    converted: list[str],
    home_count: int,
    home_nodes: list[int],
    nodes: dict[int, tuple[int, int]] | None,
) -> list[str]:
    mutable = [list(row) for row in converted]
    rows = len(mutable)
    cols = len(mutable[0]) if rows else 0

    for node_id in home_nodes:
        if nodes is None:
            raise ValueError("--home-nodes requires --nodes")
        if node_id not in nodes:
            raise ValueError(f"home node {node_id} is not present in the nodes file")
        x, y = nodes[node_id]
        if not (0 <= y < rows and 0 <= x < cols):
            raise ValueError(f"home node {node_id} has out-of-map position ({x}, {y})")
        if mutable[y][x] == "@":
            raise ValueError(f"home node {node_id} maps to obstacle cell ({x}, {y})")
        mutable[y][x] = "r"

    existing_homes = sum(row.count("r") for row in mutable)
    needed = max(0, home_count - existing_homes)
    if needed:
        for y, row in enumerate(mutable):
            for x, cell in enumerate(row):
                if cell in {"e", "."}:
                    mutable[y][x] = "r"
                    needed -= 1
                    if needed == 0:
                        break
            if needed == 0:
                break
    if needed:
        raise ValueError(f"could not place {needed} requested home cells")

    return ["".join(row) for row in mutable]


def write_rhcr_map(
    output: Path,
    rows: int,
    cols: int,
    grid: list[str],
    max_time: int,
    home_count: int,
    home_nodes: list[int],
    nodes: dict[int, tuple[int, int]] | None,
) -> None:
    converted = ["".join(convert_cell(ch) for ch in row) for row in grid]
    converted = apply_home_cells(converted, home_count, home_nodes, nodes)
    endpoints = sum(row.count("e") for row in converted)
    homes = sum(row.count("r") for row in converted)

    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w") as f:
        f.write(f"{rows},{cols}\n")
        f.write(f"{endpoints}\n")
        f.write(f"{homes}\n")
        f.write(f"{max_time}\n")
        for row in converted:
            f.write(row + "\n")

    print(f"Wrote {output}")
    print(f"rows={rows}, cols={cols}, endpoints={endpoints}, homes={homes}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=Path("maps/grid_map4.map"))
    parser.add_argument("--output", type=Path, default=Path("maps/grid_map4.rhcr.map"))
    parser.add_argument("--max-time", type=int, default=0)
    parser.add_argument("--nodes", type=Path, help="Node dictionary, needed with --home-nodes")
    parser.add_argument("--home-count", type=int, default=0, help="Ensure at least this many home cells")
    parser.add_argument(
        "--home-nodes",
        type=str,
        default="",
        help="Comma-separated NodeID values to mark as home cells",
    )
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    rows, cols, grid = read_movingai_map(args.input)
    nodes = parse_nodes(args.nodes) if args.nodes else None
    home_nodes = [int(x) for x in args.home_nodes.split(",") if x.strip()]
    write_rhcr_map(
        args.output,
        rows,
        cols,
        grid,
        args.max_time,
        args.home_count,
        home_nodes,
        nodes,
    )
