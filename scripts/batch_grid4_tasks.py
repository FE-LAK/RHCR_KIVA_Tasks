#!/usr/bin/env python3
"""Run grid4 task scenarios with one or more AGV counts and collect CSV results."""

from __future__ import annotations

import argparse
import csv
import os
import re
import subprocess
from pathlib import Path


SUMMARY_PATTERNS = {
    "makespan": re.compile(r"^Makespan time:\s*(\d+)\s*$", re.MULTILINE),
    "fleet_time": re.compile(r"^Fleet total time:\s*(\d+)\s*$", re.MULTILINE),
    "fleet_distance": re.compile(r"^Fleet total distance:\s*(\d+)\s*$", re.MULTILINE),
}
SOLVER_RUNTIME_PATTERN = re.compile(
    r"^(?:[A-Za-z0-9_*+.-]+:)?(?:Succeed|Timeout),([0-9.eE+-]+),",
    re.MULTILINE,
)


def task_sort_key(path: Path) -> tuple[int, str]:
    match = re.search(r"_(\d+)$", path.stem)
    return (int(match.group(1)) if match else 0, path.name)


def parse_summary(log: str) -> dict[str, int] | None:
    values: dict[str, int] = {}
    for name, pattern in SUMMARY_PATTERNS.items():
        matches = pattern.findall(log)
        if not matches:
            return None
        values[name] = int(matches[-1])
    return values


def parse_total_computation_time(log: str) -> float:
    return sum(float(match) for match in SOLVER_RUNTIME_PATTERN.findall(log))


def display_path(path: Path, root: Path) -> Path:
    try:
        return path.relative_to(root)
    except ValueError:
        return path


def resolve_task_filter(task: str, root: Path) -> Path:
    candidates: list[Path]
    if task.isdigit():
        candidates = [root / "maps" / f"Tasks_{task}.txt"]
    else:
        task_path = Path(task)
        candidates = [
            task_path if task_path.is_absolute() else root / task_path,
            root / "maps" / task,
        ]
        if not task.endswith(".txt"):
            candidates.append(root / "maps" / f"{task}.txt")

    for candidate in candidates:
        if candidate.is_file():
            return candidate
    choices = ", ".join(str(display_path(candidate, root)) for candidate in candidates)
    raise SystemExit(f"task file not found; tried: {choices}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tasks-glob", default="maps/Tasks_*.txt")
    parser.add_argument(
        "--task",
        help="Run one task file only. Accepts a number like 3, a name like Tasks_3.txt, or a path.",
    )
    parser.add_argument("--map", type=Path, default=Path("maps/grid_map4.map"))
    parser.add_argument("--nodes", type=Path, default=Path("maps/grid_map4.nodes.txt"))
    parser.add_argument("--workflow", type=Path, default=Path("scripts/run_grid4_workflow.sh"))
    parser.add_argument("--agents", type=int, help="Run one AGV count only")
    parser.add_argument("--min-agents", type=int, default=1)
    parser.add_argument("--max-agents", type=int, default=10)
    parser.add_argument("--simulation-time", type=int, default=2000)
    parser.add_argument("--simulation-window", type=int, default=1)
    parser.add_argument("--time-limit", type=int, default=60)
    parser.add_argument("--solver", default="ECBS")
    parser.add_argument("--single-agent-solver", default="SIPP")
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--suboptimal-bound", type=float, default=1.5)
    parser.add_argument("--map-unit-distance", type=float, default=0.5)
    parser.add_argument("--velocity", type=float, default=1.0)
    parser.add_argument(
        "--max-consecutive-timeouts",
        type=int,
        default=0,
        help="Stop a run after this many consecutive planning failures/timeouts; 0 disables",
    )
    parser.add_argument("--breakdown-agent", type=int, help="Target AGV id that breaks down")
    parser.add_argument("--breakdown-after-tasks", type=int, help="Completed pickup-delivery tasks before breakdown")
    parser.add_argument("--breakdown-location", type=int, help="Internal map location where the AGV parks")
    parser.add_argument("--runs-dir", type=Path, default=Path("batch_runs/grid4"))
    parser.add_argument("--results", type=Path, default=Path("batch_runs/grid4_results.csv"))
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.agents is not None and args.agents < 1:
        raise SystemExit("agents must be positive")
    if args.agents is None and (args.min_agents < 1 or args.max_agents < args.min_agents):
        raise SystemExit("agent range must satisfy 1 <= min-agents <= max-agents")
    if args.simulation_time < 1 or args.simulation_window < 1 or args.time_limit < 1:
        raise SystemExit("simulation-time, simulation-window, and time-limit must be positive")
    if args.map_unit_distance <= 0 or args.velocity <= 0:
        raise SystemExit("map-unit-distance and velocity must be positive")
    if args.max_consecutive_timeouts < 0:
        raise SystemExit("max-consecutive-timeouts must be non-negative")
    breakdown_values = [args.breakdown_agent, args.breakdown_after_tasks, args.breakdown_location]
    if any(value is not None for value in breakdown_values) and any(value is None for value in breakdown_values):
        raise SystemExit("breakdown-agent, breakdown-after-tasks, and breakdown-location must be supplied together")
    if args.breakdown_after_tasks is not None and args.breakdown_after_tasks < 0:
        raise SystemExit("breakdown-after-tasks must be non-negative")

    root = Path(__file__).resolve().parents[1]
    if args.task:
        task_files = [resolve_task_filter(args.task, root)]
    else:
        task_files = sorted(root.glob(args.tasks_glob), key=task_sort_key)
    if not task_files:
        raise SystemExit(f"no task files match {args.tasks_glob!r}")
    agent_counts = (
        [args.agents]
        if args.agents is not None
        else list(range(args.min_agents, args.max_agents + 1))
    )
    workflow = root / args.workflow
    if not workflow.is_file():
        raise SystemExit(f"workflow script not found: {workflow}")
    if not args.dry_run and not (root / "lifelong").is_file():
        raise SystemExit("lifelong is not built; run `make -j2` first")

    runs_dir = root / args.runs_dir
    results_path = root / args.results
    runs_dir.mkdir(parents=True, exist_ok=True)
    results_path.parent.mkdir(parents=True, exist_ok=True)

    fieldnames = [
        "task_file",
        "agents_count",
        "makespan",
        "fleet_time",
        "fleet_distance",
        "total_computation_time",
        "status",
        "log_file",
    ]
    write_header = not results_path.exists() or results_path.stat().st_size == 0
    with results_path.open("a", newline="") as results_file:
        writer = csv.DictWriter(results_file, fieldnames=fieldnames)
        if write_header:
            writer.writeheader()

        total = len(task_files) * len(agent_counts)
        run_number = 0
        for task_file in task_files:
            for agents_count in agent_counts:
                run_number += 1
                run_dir = runs_dir / task_file.stem / f"agents_{agents_count}"
                log_path = run_dir / "run.log"
                run_dir.mkdir(parents=True, exist_ok=True)
                print(f"[{run_number}/{total}] {task_file.name}, agents={agents_count}", flush=True)

                environment = os.environ.copy()
                environment.update(
                    {
                        "INPUT_MAP": str(root / args.map),
                        "NODES_FILE": str(root / args.nodes),
                        "TASKS_FILE": str(task_file),
                        "RHCR_MAP": str(run_dir / "grid_map4.rhcr.map"),
                        "RHCR_TASKS": str(run_dir / "grid_map4.rhcr.tasks.txt"),
                        "OUTPUT_DIR": str(run_dir / "output"),
                        "DECODE_TASKS": "0",
                        "SHOW_VIS": "0",
                        "EXPORT_GIF": "0",
                        "AGENTS": str(agents_count),
                        "SIMULATION_TIME": str(args.simulation_time),
                        "SIMULATION_WINDOW": str(args.simulation_window),
                        "SOLVER": args.solver,
                        "SINGLE_AGENT_SOLVER": args.single_agent_solver,
                        "TIME_LIMIT": str(args.time_limit),
                        "SEED": str(args.seed),
                        "SUBOPTIMAL_BOUND": str(args.suboptimal_bound),
                        "MAP_UNIT_DISTANCE": str(args.map_unit_distance),
                        "VELOCITY": str(args.velocity),
                        "MAX_CONSECUTIVE_TIMEOUTS": str(args.max_consecutive_timeouts),
                    }
                )
                if args.breakdown_agent is not None:
                    environment.update(
                        {
                            "BREAKDOWN_AGENT": str(args.breakdown_agent),
                            "BREAKDOWN_AFTER_TASKS": str(args.breakdown_after_tasks),
                            "BREAKDOWN_LOCATION": str(args.breakdown_location),
                        }
                    )

                if args.dry_run:
                    log_path.write_text("Dry run: workflow was not executed.\n")
                    result = {"status": "dry-run"}
                else:
                    completed = subprocess.run(
                        ["bash", str(workflow)],
                        cwd=root,
                        env=environment,
                        text=True,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.STDOUT,
                    )
                    log_path.write_text(completed.stdout)
                    summary = parse_summary(completed.stdout)
                    result = {"status": "ok" if completed.returncode == 0 and summary else "failed"}
                    if summary:
                        result.update(summary)
                    result["total_computation_time"] = parse_total_computation_time(completed.stdout)

                writer.writerow(
                    {
                        "task_file": task_file.name,
                        "agents_count": agents_count,
                        "makespan": result.get("makespan", ""),
                        "fleet_time": result.get("fleet_time", ""),
                        "fleet_distance": result.get("fleet_distance", ""),
                        "total_computation_time": result.get("total_computation_time", ""),
                        "status": result["status"],
                        "log_file": display_path(log_path, root),
                    }
                )
                results_file.flush()

    print(f"Wrote results to {results_path}")


if __name__ == "__main__":
    main()
