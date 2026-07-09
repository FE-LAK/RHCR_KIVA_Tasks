# Test scripts

python3 scripts/batch_grid4_tasks.py   --simulation-time 3500   --time-limit 10   --solver ECBS   --runs-dir results/grid4_runs   --results results/grid4_summary.csv --task 1

Break down AGV 0 after it completes 3 pickup-delivery tasks, then send it to internal map location 38:

```bash
BREAKDOWN_AGENT=0 \
BREAKDOWN_AFTER_TASKS=3 \
BREAKDOWN_LOCATION=38 \
bash scripts/run_grid4_workflow.sh
```

The same parameters are available in batch runs:

```bash
python3 scripts/batch_grid4_tasks.py \
  --task 1 \
  --agents 10 \
  --breakdown-agent 0 \
  --breakdown-after-tasks 3 \
  --breakdown-location 38
```


python3 scripts/plot_grid4_results.py results/grid4_summary.csv --output results/grid4_plots.png


python3 scripts/batch_grid4_tasks.py   --simulation-time 3500   --time-limit 10   --solver ECBS   --runs-dir results/grid4_runs   --results results/grid4_summary.csv --task 1
  
python3 scripts/visualize_kiva.py   --map results/grid4_runs/Tasks_1/agents_1/grid_map4.rhcr.map   --output results/grid4_runs/Tasks_1/agents_14/output   --tasks results/grid4_runs/Tasks_1/agents_14/grid_map4.rhcr.tasks.txt   --original-tasks maps/Tasks_1.txt   --packages   --labels   --dpi 80   --fps 2   --save task14ag.gif

## For GK map:
Without obstacles
```
python3 scripts/batch_grid4_tasks.py --tasks-glob "maps/gk/tasks_*.txt" --workflow scripts/run_grid4_workflow.sh --min-agents 1  --max-agents 20 --time-limit 10 --map maps/gk/grid_map_gk.map --nodes maps/gk/grid_map_gk.nodes.txt --max-consecutive-timeouts 5 --runs-dir batch_runs/grid4_obstacle --results batch_runs/grid4_gk_results.csv
```

With obstacles
```
python3 scripts/batch_grid4_tasks.py --tasks-glob "maps/gk/tasks_*.txt" --workflow scripts/run_grid4_workflow.sh --min-agents 1  --max-agents 20 --time-limit 10 --map maps/gk/grid_map_gk.map --nodes maps/gk/grid_map_gk.nodes.txt --max-consecutive-timeouts 5 --runs-dir batch_runs/grid4_obstacle --results batch_runs/grid4_gk_obstacle_results.csv --breakdown-agent 0 --breakdown-after-tasks 0 --breakdown-location 574
```