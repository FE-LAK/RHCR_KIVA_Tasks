


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


python3 scripts/plot_grid4_results.py results/grid4_summary.csv \
  --output results/grid4_plots.png