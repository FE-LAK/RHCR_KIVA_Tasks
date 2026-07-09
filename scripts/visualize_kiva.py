#!/usr/bin/env python3
"""Animate RHCR KIVA/SORTING paths saved by BasicSystem::save_results()."""

from __future__ import annotations

import argparse
import csv
import os
import re
import tempfile
from pathlib import Path

os.environ.setdefault("MPLCONFIGDIR", str(Path(tempfile.gettempdir()) / "rhcr_matplotlib"))

import matplotlib.pyplot as plt
from matplotlib.animation import FuncAnimation
from matplotlib.colors import ListedColormap
from matplotlib.patches import Rectangle
import numpy as np
from PIL import GifImagePlugin, Image


STATE_RE = re.compile(r"(-?\d+),(-?\d+),(-?\d+)")
PACKAGE_COLORS = [
    (0.902, 0.624, 0.000),  # orange
    (0.337, 0.706, 0.914),  # sky blue
    (0.000, 0.620, 0.451),  # bluish green
    (0.941, 0.894, 0.259),  # yellow
    (0.000, 0.447, 0.698),  # blue
    (0.835, 0.369, 0.000),  # vermillion
    (0.800, 0.475, 0.655),  # reddish purple
    (0.350, 0.350, 0.350),  # gray
]


def resolve_result_file(output: Path, name: str) -> Path:
    candidates = [
        output / name,
        Path(str(output) + "\\" + name),
        Path(str(output) + "/" + name),
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    raise FileNotFoundError(
        f"Could not find {name}. Tried: " + ", ".join(str(c) for c in candidates)
    )


def load_map(path: Path) -> tuple[int, int, list[str]]:
    if path.suffix == ".map":
        lines = path.read_text().splitlines()
        first = lines[0].replace(",", " ").split()
        if first and first[0].isdigit():
            rows, cols = [int(x) for x in first[:2]]
            grid = lines[4 : 4 + rows]
            return map_body_to_types(rows, cols, grid)
        return load_movingai_map(lines)

    if path.suffix == ".grid":
        with path.open(newline="") as f:
            next(f)
            rows, cols = [int(x) for x in next(csv.reader([f.readline()]))[:2]]
            next(f)
            types = ["Travel"] * (rows * cols)
            reader = csv.reader(f)
            for row in reader:
                if len(row) >= 2:
                    types[int(row[0])] = row[1]
            return rows, cols, types

    raise ValueError("Map must end in .map or .grid")


def load_movingai_map(lines: list[str]) -> tuple[int, int, list[str]]:
    rows = cols = None
    map_start = None
    for i, line in enumerate(lines):
        parts = line.split()
        if len(parts) == 2 and parts[0].lower() == "height":
            rows = int(parts[1])
        elif len(parts) == 2 and parts[0].lower() == "width":
            cols = int(parts[1])
        elif len(parts) == 1 and parts[0].lower() == "map":
            map_start = i + 1
            break
    if rows is None or cols is None or map_start is None:
        raise ValueError("Could not parse .map as RHCR custom or MovingAI format")
    return map_body_to_types(rows, cols, lines[map_start : map_start + rows])


def map_body_to_types(rows: int, cols: int, grid: list[str]) -> tuple[int, int, list[str]]:
    if len(grid) != rows:
        raise ValueError(f"Expected {rows} map rows, found {len(grid)}")
    types = []
    for row in grid:
        if len(row) < cols:
            raise ValueError(f"Map row is shorter than width {cols}: {row}")
        for ch in row[:cols]:
            if ch == "@":
                types.append("Obstacle")
            elif ch in {"e", "E"}:
                types.append("Endpoint")
            elif ch in {"r", "R"}:
                types.append("Home")
            else:
                types.append("Travel")
    return rows, cols, types


def load_paths(path: Path) -> list[list[tuple[int, int, int]]]:
    lines = path.read_text().splitlines()
    if not lines:
        raise ValueError(f"{path} is empty")
    paths = []
    for line in lines[1:]:
        states = []
        for loc, orientation, timestep in STATE_RE.findall(line):
            loc_i = int(loc)
            if loc_i >= 0:
                states.append((loc_i, int(orientation), int(timestep)))
        paths.append(states)
    return paths


def load_delivery_sequences(path: Path | None) -> list[int]:
    if path is None:
        return []
    sequences = []
    for raw_line in path.read_text().splitlines():
        line = raw_line.split("#", 1)[0].strip()
        if not line:
            continue
        values = [int(x) for x in re.split(r"[\s,;:]+", line) if x]
        if len(values) >= 7:
            sequences.append(values[6])
    return sequences


def load_packages(path: Path | None, delivery_sequences: list[int] | None = None) -> list[dict[str, int]]:
    if path is None:
        return []
    delivery_sequences = delivery_sequences or []
    packages = []
    package_id = 0
    for line_no, raw_line in enumerate(path.read_text().splitlines(), start=1):
        line = raw_line.split("#", 1)[0].strip()
        if not line:
            continue
        values = [int(x) for x in re.split(r"[\s,;:]+", line) if x]
        if len(values) < 3 or len(values) % 2 == 0:
            raise ValueError(
                f"{path}:{line_no}: expected agent_id pickup delivery [pickup delivery ...]"
            )
        agent_hint = values[0]
        for i in range(1, len(values), 2):
            packages.append(
                {
                    "id": package_id,
                    "agent_hint": agent_hint,
                    "pickup": values[i],
                    "delivery": values[i + 1],
                    "delivery_sequence": delivery_sequences[package_id]
                    if package_id < len(delivery_sequences)
                    else package_id,
                }
            )
            package_id += 1
    return packages


def load_task_records(path: Path) -> list[list[tuple[int, int]]]:
    lines = path.read_text().splitlines()
    records_by_agent: list[list[tuple[int, int]]] = []
    for raw_line in lines[1:]:
        records: list[tuple[int, int]] = []
        for item in raw_line.split(";"):
            parts = [part for part in item.split(",") if part != ""]
            if len(parts) >= 2:
                records.append((int(parts[0]), int(parts[1])))
        records_by_agent.append(records)
    return records_by_agent


def build_package_events(
    packages: list[dict[str, int]],
    task_records: list[list[tuple[int, int]]],
) -> list[dict[str, object]]:
    assignment_queues = {loc: list(queue) for loc, queue in initial_package_queues(packages).items()}
    pickup_events: list[dict[str, int]] = []
    events: list[dict[str, object]] = []

    for agent, records in enumerate(task_records):
        goal_records = records[1:]  # first entry is the initial home location
        for i in range(0, len(goal_records), 2):
            pickup_loc, pickup_time = goal_records[i]
            if pickup_time < 0:
                continue
            delivery_loc = -1
            delivery_time = -1
            if i + 1 < len(goal_records):
                delivery_loc, delivery_time = goal_records[i + 1]
            pickup_events.append(
                {
                    "agent": agent,
                    "pickup_loc": pickup_loc,
                    "pickup_time": pickup_time,
                    "delivery_loc": delivery_loc,
                    "delivery_time": delivery_time,
                }
            )

    for pickup_event in sorted(
        pickup_events,
        key=lambda e: (e["pickup_time"], e["delivery_time"], e["agent"]),
    ):
        pickup_loc = pickup_event["pickup_loc"]
        package = pop_bottom_package(assignment_queues.setdefault(pickup_loc, []))
        if package is None:
            # Records can contain operational goals, such as breakdown parking
            # or final return locations. They are not packages.
            continue
        events.append(
            {
                "agent": pickup_event["agent"],
                "package": package,
                "pickup_time": pickup_event["pickup_time"],
                "delivery_time": pickup_event["delivery_time"],
                "delivery_loc": pickup_event["delivery_loc"],
            }
        )

    return events


def pop_bottom_package(queue: list[dict[str, int]]) -> dict[str, int] | None:
    if not queue:
        return None
    return queue.pop(0)


def initial_package_queues(packages: list[dict[str, int]]) -> dict[int, list[dict[str, int]]]:
    queues: dict[int, list[dict[str, int]]] = {}
    for package in packages:
        queues.setdefault(package["pickup"], []).append(package)
    return queues


def package_snapshot(
    packages: list[dict[str, int]],
    events: list[dict[str, object]],
    timestep: int,
) -> tuple[dict[int, list[dict[str, int]]], dict[int, list[dict[str, int]]], dict[int, dict[str, int]]]:
    queues = {loc: list(queue) for loc, queue in initial_package_queues(packages).items()}
    delivery_queues = {package["delivery"]: [] for package in packages}
    carried: dict[int, dict[str, int]] = {}

    for event in sorted(events, key=lambda e: (int(e["pickup_time"]), int(e["agent"]))):
        pickup_time = int(event["pickup_time"])
        if pickup_time > timestep:
            continue
        agent = int(event["agent"])
        package = event["package"]
        assert isinstance(package, dict)
        remove_package_from_queue(queues.setdefault(package["pickup"], []), package["id"])
        delivery_time = int(event["delivery_time"])
        delivery_loc = int(event["delivery_loc"])
        if delivery_time >= 0 and delivery_time <= timestep:
            delivery_queues.setdefault(delivery_loc, []).insert(0, package)
            carried.pop(agent, None)
        else:
            carried[agent] = package

    return queues, delivery_queues, carried


def remove_package_from_queue(queue: list[dict[str, int]], package_id: int) -> None:
    for i, package in enumerate(queue):
        if package["id"] == package_id:
            queue.pop(i)
            return


def state_at(path: list[tuple[int, int, int]], timestep: int) -> tuple[int, int, int] | None:
    if not path:
        return None
    if timestep < len(path) and path[timestep][2] == timestep:
        return path[timestep]
    if timestep >= path[-1][2]:
        return path[-1]
    for state in path:
        if state[2] == timestep:
            return state
    return None


def make_background(rows: int, cols: int, types: list[str]) -> np.ndarray:
    values = np.zeros((rows, cols), dtype=int)
    for loc, kind in enumerate(types):
        r, c = divmod(loc, cols)
        if kind == "Obstacle":
            values[r, c] = 1
    return values


def animate(args: argparse.Namespace) -> None:
    rows, cols, types = load_map(args.map)
    paths_file = args.paths or resolve_result_file(args.output, "paths.txt")
    paths = load_paths(paths_file)
    package_file = args.tasks or find_default_task_file(args.output)
    delivery_sequences = load_delivery_sequences(args.original_tasks)
    packages = load_packages(package_file, delivery_sequences) if args.packages else []
    task_events: list[dict[str, object]] = []
    if packages:
        task_records = load_task_records(resolve_result_file(args.output, "tasks.txt"))
        task_events = build_package_events(packages, task_records)
    max_timestep = max((p[-1][2] for p in paths if p), default=0)
    end_timestep = min(args.until, max_timestep) if args.until is not None else max_timestep

    fig, ax = plt.subplots(figsize=(args.width, args.height))
    cmap = ListedColormap(["#f7f7f2", "#242424"])
    ax.imshow(make_background(rows, cols, types), cmap=cmap, interpolation="nearest")
    ax.tick_params(left=False, bottom=False, labelleft=False, labelbottom=False)
    ax.set_xlim(-0.5, cols - 0.5)
    top_y = -0.5
    if packages:
        buffer_locations = {p["pickup"] for p in packages} | {p["delivery"] for p in packages}
        if buffer_locations:
            top_row = min(loc // cols for loc in buffer_locations)
            top_y = min(top_y, top_row - args.buffer_capacity - 0.5)
    ax.set_ylim(rows - 0.5, top_y)

    colors = plt.cm.tab20(np.linspace(0, 1, max(1, len(paths))))
    scatter = ax.scatter([], [], s=args.agent_size, c=[], edgecolors="black", linewidths=0.5)
    labels = [ax.text(0, 0, "", ha="center", va="center", fontsize=7) for _ in paths]
    title = ax.set_title("")
    package_artists: list[Rectangle] = []

    def clear_packages() -> None:
        while package_artists:
            package_artists.pop().remove()

    def draw_buffer(loc: int) -> None:
        r, c = divmod(loc, cols)
        artist = Rectangle(
            (c - 0.5, r - args.buffer_capacity - 0.5),
            1.0,
            float(args.buffer_capacity),
            facecolor="none",
            edgecolor="#3f3f3f",
            linewidth=1.2,
            zorder=3,
        )
        ax.add_patch(artist)
        package_artists.append(artist)

    def draw_queued_package(loc: int, depth: int, package: dict[str, int]) -> None:
        r, c = divmod(loc, cols)
        y = r - depth - 1.5
        artist = Rectangle(
            (c - 0.5, y),
            1.0,
            1.0,
            facecolor=package_color(package["delivery_sequence"]),
            edgecolor="#1f1f1f",
            linewidth=0.5,
            zorder=4,
        )
        ax.add_patch(artist)
        package_artists.append(artist)

    def draw_carried_package(agent_loc: int, package: dict[str, int]) -> None:
        r, c = divmod(agent_loc, cols)
        artist = Rectangle(
            (c - 0.5, r - 0.5),
            1.0,
            1.0,
            facecolor=package_color(package["delivery_sequence"]),
            edgecolor="#1f1f1f",
            linewidth=0.8,
            alpha=0.82,
            zorder=6,
        )
        ax.add_patch(artist)
        package_artists.append(artist)

    def package_color(delivery_sequence: int):
        return PACKAGE_COLORS[(delivery_sequence - 1) % len(PACKAGE_COLORS)]

    def update(timestep: int):
        clear_packages()
        xs, ys, cs = [], [], []
        agent_locations: dict[int, int] = {}
        for agent, path in enumerate(paths):
            state = state_at(path, timestep)
            if state is None:
                labels[agent].set_text("")
                continue
            loc, _, _ = state
            agent_locations[agent] = loc
            r, c = divmod(loc, cols)
            xs.append(c)
            ys.append(r)
            cs.append(colors[agent % len(colors)])
            labels[agent].set_position((c, r))
            labels[agent].set_text(str(agent) if args.labels else "")
        if packages:
            queues, delivery_queues, carried = package_snapshot(packages, task_events, timestep)
            for loc in sorted({p["pickup"] for p in packages} | {p["delivery"] for p in packages}):
                draw_buffer(loc)
            for loc, queue in queues.items():
                for depth, package in enumerate(queue[: args.buffer_capacity]):
                    draw_queued_package(loc, depth, package)
            for loc, queue in delivery_queues.items():
                for depth, package in enumerate(queue[: args.buffer_capacity]):
                    draw_queued_package(loc, depth, package)
            for agent, package in carried.items():
                if agent in agent_locations:
                    draw_carried_package(agent_locations[agent], package)
        scatter.set_offsets(np.c_[xs, ys] if xs else np.empty((0, 2)))
        scatter.set_color(cs)
        title.set_text(f"t = {timestep} / {end_timestep}")
        return [scatter, title, *labels, *package_artists]

    frames = range(args.start, end_timestep + 1)
    if args.save and args.save.suffix.lower() == ".gif":
        palette = make_gif_palette(len(paths))
        save_streaming_gif(fig, update, frames, args.save, args.fps, args.dpi, args.repeat, palette)
        plt.close(fig)
        return

    anim = FuncAnimation(
        fig,
        update,
        frames=frames,
        interval=1000 / args.fps,
        blit=False,
        repeat=args.repeat,
        cache_frame_data=False,
    )

    if args.save:
        anim.save(args.save, fps=args.fps, dpi=args.dpi)
    else:
        plt.show()


def save_streaming_gif(
    fig,
    update,
    frames,
    path: Path,
    fps: int,
    dpi: int,
    repeat: bool,
    palette: Image.Image,
) -> None:
    duration = max(1, int(round(1000 / fps)))
    fig.set_dpi(dpi)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("wb") as f:
        wrote_header = False
        for index, timestep in enumerate(frames):
            update(timestep)
            fig.canvas.draw()
            image = Image.fromarray(np.asarray(fig.canvas.buffer_rgba())).convert("RGB")
            image = image.quantize(palette=palette, dither=Image.Dither.NONE)
            image.info["duration"] = duration
            if repeat:
                image.info["loop"] = 0
            if not wrote_header:
                write_gif_chunks(f, GifImagePlugin.getheader(image, info=image.info))
                wrote_header = True
            write_gif_chunks(f, GifImagePlugin.getdata(image, duration=duration))
            if index and index % 100 == 0:
                print(f"Saved {index} GIF frames...", flush=True)
        f.write(b";")


def make_gif_palette(agent_count: int) -> Image.Image:
    colors: list[tuple[int, int, int]] = []
    for color in [
        "#f7f7f2",
        "#242424",
        "#000000",
        "#1f1f1f",
        "#3f3f3f",
        "#ffffff",
    ]:
        colors.append(hex_to_rgb(color))
    colors.extend(rgba_to_rgb(plt.cm.tab20(i)) for i in np.linspace(0, 1, max(1, agent_count)))
    colors.extend(float_rgb_to_rgb(color) for color in PACKAGE_COLORS)

    palette_values: list[int] = []
    seen: set[tuple[int, int, int]] = set()
    for color in colors:
        if color in seen:
            continue
        seen.add(color)
        palette_values.extend(color)
    while len(palette_values) < 256 * 3:
        palette_values.extend((0, 0, 0))
    palette = Image.new("P", (1, 1))
    palette.putpalette(palette_values[: 256 * 3])
    return palette


def hex_to_rgb(color: str) -> tuple[int, int, int]:
    color = color.lstrip("#")
    return tuple(int(color[i : i + 2], 16) for i in (0, 2, 4))


def rgba_to_rgb(color) -> tuple[int, int, int]:
    return tuple(int(round(channel * 255)) for channel in color[:3])


def float_rgb_to_rgb(color: tuple[float, float, float]) -> tuple[int, int, int]:
    return tuple(int(round(channel * 255)) for channel in color)


def write_gif_chunks(handle, chunks) -> None:
    for chunk in chunks:
        if chunk is None:
            continue
        if isinstance(chunk, (list, tuple)):
            write_gif_chunks(handle, chunk)
        else:
            handle.write(chunk)


def find_default_task_file(output: Path) -> Path | None:
    for name in ("task_assignments.txt", "rhcr.tasks.txt"):
        candidate = output / name
        if candidate.exists():
            return candidate
    return None


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--map", type=Path, required=True, help="Input .map or .grid file")
    parser.add_argument("--output", type=Path, default=Path("../exp/test"), help="RHCR output directory")
    parser.add_argument("--paths", type=Path, help="Explicit paths.txt file")
    parser.add_argument("--start", type=int, default=0, help="First timestep to show")
    parser.add_argument("--until", type=int, help="Last timestep to show")
    parser.add_argument("--fps", type=int, default=8, help="Animation frames per second")
    parser.add_argument("--save", type=Path, help="Save to .mp4 or .gif instead of opening a window")
    parser.add_argument("--dpi", type=int, default=140, help="Output DPI when saving")
    parser.add_argument("--width", type=float, default=8, help="Figure width in inches")
    parser.add_argument("--height", type=float, default=8, help="Figure height in inches")
    parser.add_argument("--agent-size", type=float, default=90, help="Marker size")
    parser.add_argument("--labels", action="store_true", help="Draw agent ids")
    parser.add_argument("--tasks", type=Path, help="RHCR pickup-delivery task file")
    parser.add_argument("--original-tasks", type=Path, help="Original task file with delivery sequence column")
    parser.add_argument("--packages", action="store_true", help="Draw pickup queues and carried packages")
    parser.add_argument("--buffer-capacity", type=int, default=7, help="Visible package slots per queue buffer")
    parser.add_argument("--repeat", action="store_true", help="Loop the animation")
    return parser.parse_args()


if __name__ == "__main__":
    animate(parse_args())
