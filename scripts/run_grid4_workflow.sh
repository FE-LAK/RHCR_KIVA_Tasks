#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

INPUT_MAP="${INPUT_MAP:-maps/grid_map4.map}"
NODES_FILE="${NODES_FILE:-maps/grid_map4.nodes.txt}"
TASKS_FILE="${TASKS_FILE:-maps/Tasks_1.txt}"
RHCR_MAP="${RHCR_MAP:-maps/grid_map4.rhcr.map}"
RHCR_TASKS="${RHCR_TASKS:-maps/grid_map4.rhcr.tasks.txt}"
DECODED_TASKS="${DECODED_TASKS:-/tmp/rhcr_grid4_decoded_tasks.txt}"
OUTPUT_DIR="${OUTPUT_DIR:-/tmp/rhcr_grid4_run}"
GIF_FILE="${GIF_FILE:-/tmp/rhcr_grid4_run.gif}"
EXPORT_GIF="${EXPORT_GIF:-1}"
DECODE_TASKS="${DECODE_TASKS:-1}"

AGENTS="${AGENTS:-5}"
HOME_COUNT="$AGENTS"
if (( HOME_COUNT < 2 )); then
  HOME_COUNT=2
fi
SIMULATION_TIME="${SIMULATION_TIME:-1590}"
SIMULATION_WINDOW="${SIMULATION_WINDOW:-1}"
PLANNING_WINDOW="${PLANNING_WINDOW:-}"
SOLVER="${SOLVER:-ECBS}"
SINGLE_AGENT_SOLVER="${SINGLE_AGENT_SOLVER:-SIPP}"
TIME_LIMIT="${TIME_LIMIT:-60}"
SEED="${SEED:-0}"
SUBOPTIMAL_BOUND="${SUBOPTIMAL_BOUND:-1.5}"
MAP_UNIT_DISTANCE="${MAP_UNIT_DISTANCE:-0.5}"
VELOCITY="${VELOCITY:-1.0}"
MAX_CONSECUTIVE_TIMEOUTS="${MAX_CONSECUTIVE_TIMEOUTS:-10}"
BREAKDOWN_AGENT="${BREAKDOWN_AGENT:-}"
BREAKDOWN_AFTER_TASKS="${BREAKDOWN_AFTER_TASKS:-}"
BREAKDOWN_LOCATION="${BREAKDOWN_LOCATION:-}"
DUMMY_PATHS=0
HOLD_ENDPOINTS=0
FPS="${FPS:-30}"
VIS_UNTIL="${VIS_UNTIL:-$SIMULATION_TIME}"
BUFFER_CAPACITY="${BUFFER_CAPACITY:-7}"
SHOW_VIS="${SHOW_VIS:-0}"

echo "==> Converting map"
python3 scripts/convert_map.py \
  --input "$INPUT_MAP" \
  --output "$RHCR_MAP" \
  --home-count "$HOME_COUNT"

echo "==> Converting tasks"
python3 scripts/convert_tasks.py \
  --tasks "$TASKS_FILE" \
  --nodes "$NODES_FILE" \
  --map "$INPUT_MAP" \
  --output "$RHCR_TASKS"

if [[ "$DECODE_TASKS" == "1" ]]; then
  echo "==> Decoding exported tasks to original NodeIDs"
  python3 scripts/decode_tasks.py \
    --tasks "$RHCR_TASKS" \
    --map "$INPUT_MAP" \
    --nodes "$NODES_FILE" \
    --output "$DECODED_TASKS"
fi

echo "==> Running RHCR/lifelong"
echo "    simulation_time cap: $SIMULATION_TIME"
cmd=(
  ./lifelong
  -m "$RHCR_MAP"
  -k "$AGENTS"
  --scenario=KIVA
  --task "$RHCR_TASKS"
  --simulation_window="$SIMULATION_WINDOW"
  --solver="$SOLVER"
  --single_agent_solver="$SINGLE_AGENT_SOLVER"
  --cutoffTime="$TIME_LIMIT"
  --seed="$SEED"
  --simulation_time="$SIMULATION_TIME"
  --suboptimal_bound="$SUBOPTIMAL_BOUND"
  --map_unit_distance="$MAP_UNIT_DISTANCE"
  --velocity="$VELOCITY"
  --max_consecutive_timeouts="$MAX_CONSECUTIVE_TIMEOUTS"
  --dummy_paths="$DUMMY_PATHS"
  --hold_endpoints="$HOLD_ENDPOINTS"
  -o "$OUTPUT_DIR"
)

if [[ -n "$PLANNING_WINDOW" ]]; then
  cmd+=(--planning_window="$PLANNING_WINDOW")
fi
if [[ -n "$BREAKDOWN_AGENT" ]]; then
  cmd+=(--breakdown_agent="$BREAKDOWN_AGENT")
fi
if [[ -n "$BREAKDOWN_AFTER_TASKS" ]]; then
  cmd+=(--breakdown_after_tasks="$BREAKDOWN_AFTER_TASKS")
fi
if [[ -n "$BREAKDOWN_LOCATION" ]]; then
  cmd+=(--breakdown_location="$BREAKDOWN_LOCATION")
fi

"${cmd[@]}"

if [[ "$EXPORT_GIF" == "1" ]]; then
  echo "==> Exporting GIF"
  python3 scripts/visualize_kiva.py \
    --map "$RHCR_MAP" \
    --output "$OUTPUT_DIR" \
    --tasks "$RHCR_TASKS" \
    --original-tasks "$TASKS_FILE" \
    --packages \
    --buffer-capacity "$BUFFER_CAPACITY" \
    --until "$VIS_UNTIL" \
    --fps "$FPS" \
    --labels \
    --save "$GIF_FILE"
else
  echo "==> Skipping GIF export"
fi

if [[ "$SHOW_VIS" == "1" ]]; then
  echo "==> Opening interactive visualization"
  python3 scripts/visualize_kiva.py \
    --map "$RHCR_MAP" \
    --output "$OUTPUT_DIR" \
    --tasks "$RHCR_TASKS" \
    --original-tasks "$TASKS_FILE" \
    --packages \
    --buffer-capacity "$BUFFER_CAPACITY" \
    --until "$VIS_UNTIL" \
    --fps "$FPS" \
    --labels
fi

echo "==> Done"
echo "Converted map:   $RHCR_MAP"
echo "Converted tasks: $RHCR_TASKS"
if [[ "$DECODE_TASKS" == "1" ]]; then
  echo "Decoded tasks:   $DECODED_TASKS"
fi
echo "Run output:      $OUTPUT_DIR"
if [[ "$EXPORT_GIF" == "1" ]]; then
  echo "GIF:             $GIF_FILE"
fi
echo "Buffer capacity: $BUFFER_CAPACITY"
