#!/usr/bin/env python3
"""Plot grid4 batch results by task scenario."""

from __future__ import annotations

import argparse
import csv
import os
import warnings
from collections import defaultdict
from pathlib import Path


def resolve_summary_path(results: Path, csv_name: str) -> Path:
    if results.is_file():
        return results

    candidates = [
        results / csv_name,
        results / "grid4_summary.csv",
        results / "grid4_results.csv",
        results / "summary.csv",
    ]
    for candidate in candidates:
        if candidate.is_file():
            return candidate

    tried = ", ".join(str(path) for path in candidates)
    raise SystemExit(f"could not find a summary CSV; tried: {tried}")


def task_sort_key(task_file: str) -> tuple[int, str]:
    stem = Path(task_file).stem
    prefix, _, number = stem.rpartition("_")
    if prefix and number.isdigit():
        return int(number), task_file
    return 0, task_file


def parse_float(value: str) -> float | None:
    value = value.strip()
    if not value:
        return None
    try:
        return float(value)
    except ValueError:
        return None


def load_results(summary_path: Path) -> dict[str, list[dict[str, float]]]:
    required = {"task_file", "agents_count", "makespan", "total_computation_time"}
    rows_by_task_agent: dict[tuple[str, int], dict[str, float]] = {}

    with summary_path.open(newline="") as csv_file:
        reader = csv.DictReader(csv_file)
        if reader.fieldnames is None or not required.issubset(reader.fieldnames):
            found = ", ".join(reader.fieldnames or [])
            raise SystemExit(f"{summary_path} is missing required columns; found: {found}")

        for row in reader:
            agents = parse_float(row.get("agents_count", ""))
            makespan = parse_float(row.get("makespan", ""))
            total_time = parse_float(row.get("total_computation_time", ""))
            task_file = row.get("task_file", "").strip()
            if not task_file or agents is None or makespan is None or total_time is None:
                continue

            # Appended result files may contain repeated runs. Keep the latest row.
            rows_by_task_agent[(task_file, int(agents))] = {
                "agents_count": int(agents),
                "makespan": makespan,
                "total_computation_time": total_time,
            }

    grouped: dict[str, list[dict[str, float]]] = defaultdict(list)
    for (task_file, _agents), values in rows_by_task_agent.items():
        grouped[task_file].append(values)

    for values in grouped.values():
        values.sort(key=lambda item: item["agents_count"])
    return dict(sorted(grouped.items(), key=lambda item: task_sort_key(item[0])))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "results",
        type=Path,
        nargs="?",
        default=Path("results"),
        help="Results folder or summary CSV path. Defaults to results/",
    )
    parser.add_argument("--csv-name", default="grid4_summary.csv")
    parser.add_argument("--output", type=Path, help="Output image path")
    parser.add_argument("--show", action="store_true", help="Open an interactive plot window")
    parser.add_argument("--dpi", type=int, default=160)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    summary_path = resolve_summary_path(args.results, args.csv_name)
    output_path = args.output
    if output_path is None:
        output_path = summary_path.with_name(summary_path.stem + "_plot.png")

    os.environ.setdefault("MPLCONFIGDIR", "/tmp/rhcr_matplotlib")
    Path(os.environ["MPLCONFIGDIR"]).mkdir(parents=True, exist_ok=True)
    warnings.filterwarnings("ignore", message="Unable to import Axes3D.*")

    if not args.show:
        import matplotlib

        matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    grouped = load_results(summary_path)
    if not grouped:
        raise SystemExit(f"no complete rows to plot in {summary_path}")

    fig, (makespan_ax, time_ax) = plt.subplots(1, 2, figsize=(13, 5))

    for task_file, values in grouped.items():
        agents = [item["agents_count"] for item in values]
        makespan = [item["makespan"] for item in values]
        total_time = [item["total_computation_time"] for item in values]
        makespan_ax.plot(agents, makespan, marker="o", linewidth=1.8, markersize=4, label=task_file)
        time_ax.plot(agents, total_time, marker="o", linewidth=1.8, markersize=4, label=task_file)

    makespan_ax.set_title("Makespan vs Agent Count")
    makespan_ax.set_xlabel("Agents")
    makespan_ax.set_ylabel("Makespan (steps)")
    makespan_ax.grid(True, alpha=0.25)

    time_ax.set_title("Computation Time vs Agent Count")
    time_ax.set_xlabel("Agents")
    time_ax.set_ylabel("Total computation time (s)")
    time_ax.grid(True, alpha=0.25)

    handles, labels = makespan_ax.get_legend_handles_labels()
    fig.legend(handles, labels, loc="lower center", ncol=min(5, max(1, len(labels))))
    fig.suptitle(f"Grid4 Batch Results: {summary_path}", fontsize=12)
    fig.tight_layout(rect=(0, 0.16, 1, 0.94))

    output_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output_path, dpi=args.dpi)
    print(f"Wrote {output_path}")

    if args.show:
        plt.show()


if __name__ == "__main__":
    main()
