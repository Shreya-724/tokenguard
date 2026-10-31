# Algorithm benchmarks

Not measured yet. On your machine, with Redis running:

```powershell
python benchmarks/algo_bench.py redis://127.0.0.1:6379/5 --docs docs
```

That replaces this page with the measured tables and writes
`docs/algorithm-benchmarks.svg`, the chart it shows. The raw numbers are saved
under `benchmarks/results/algos-<time>/`.
