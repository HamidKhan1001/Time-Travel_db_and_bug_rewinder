# Phase 7 Benchmark Report — Database Recovery Performance

## Status

**Phase 7 complete.** All numbers below come from actual benchmark executions recorded in `benchmarks/benchmark_results.json`. No estimates, synthetic timings, or artificial delays were used.

Raw data: `benchmarks/benchmark_results.json`  
Benchmark runner: `benchmarks/benchmark_recovery.py`  
Dataset generator: `benchmarks/generate_data.py`

## Environment

| Field | Value |
|---|---|
| Captured at (UTC) | 2026-11-22T01:02:48+00:00 |
| OS | macOS 13.7.8 |
| Architecture | x86_64 |
| CPU | Intel(R) Core(TM) i5-7360U CPU @ 2.30GHz |
| Logical CPUs | 4 |
| Total memory | 8.0 GB |
| Python | 3.14.6 |
| SQLite | 3.53.2 |
| Git commit at run time | `5d1e083` |

## Methodology

- Datasets: 1,000 / 10,000 / 100,000 / 500,000 inventory rows.
- Dataset shape: `N inventory rows plus 10 customers, 20 orders, and 20 order items`.
- Deterministic seed: `20261122`; fixed clock offset during generation and fault capture.
- Faulty operation: `UPDATE inventory SET stock = 0` in one explicit transaction.
- Iterations: 3 per dataset, 12 recovery executions total.
- Each iteration: generate data → create snapshot → capture history → faulty transaction → build scoped recovery plan → execute recovery with checksum verification → validate recovered stock values and audit status.
- `recovery_execution_seconds` excludes live checksum verification but includes preflight, simulation, apply, and commit.
- `recovery_duration_seconds` is wall-clock time from snapshot creation through `execute_plan()`.
- Memory is `resource.getrusage` process high-water RSS; it is cumulative within the process and is not a per-iteration delta.
- Every iteration was committed and reported `integrity_status: VERIFIED`; there were 0 errors.

## Pre-run optimization

Before the final benchmark, `verification.compare_baselines()` was changed from cross-database SQL sample queries to a single streaming merge of the two sorted checksum tables. This removed a pathological scan path: an isolated 10,000-row verification profile dropped from roughly 78.4 seconds to 2.14 seconds. The final numbers below include this optimization.

## Results

### End-to-end timing summary

All values are seconds.

| Metric | Dataset | Average | Median |
|---|---|---:|---:|
| Snapshot creation | 1,000 | 0.020260 | 0.017373 |
| Snapshot creation | 10,000 | 0.183084 | 0.138030 |
| Snapshot creation | 100,000 | 1.486343 | 1.377057 |
| Snapshot creation | 500,000 | 4.514747 | 4.023677 |
| Transaction history generation | 1,000 | 0.124949 | 0.136832 |
| Transaction history generation | 10,000 | 1.471037 | 1.301207 |
| Transaction history generation | 100,000 | 16.137999 | 19.819071 |
| Transaction history generation | 500,000 | 40.215221 | 35.239706 |
| Recovery planning | 1,000 | 0.076128 | 0.072466 |
| Recovery planning | 10,000 | 1.380139 | 1.302022 |
| Recovery planning | 100,000 | 41.588600 | 13.942961 |
| Recovery planning | 500,000 | 39.874802 | 40.545273 |
| Recovery execution | 1,000 | 1.535354 | 1.702779 |
| Recovery execution | 10,000 | 23.135158 | 22.913223 |
| Recovery execution | 100,000 | 209.658956 | 205.588705 |
| Recovery execution | 500,000 | 526.845198 | 493.732372 |
| Checksum verification | 1,000 | 0.169217 | 0.164856 |
| Checksum verification | 10,000 | 2.364991 | 2.220250 |
| Checksum verification | 100,000 | 14.419578 | 13.101422 |
| Checksum verification | 500,000 | 59.878072 | 63.025783 |
| **Total recovery duration** | **1,000** | **1.958687** | **2.185059** |
| **Total recovery duration** | **10,000** | **28.856188** | **28.365067** |
| **Total recovery duration** | **100,000** | **286.631435** | **347.718108** |
| **Total recovery duration** | **500,000** | **684.795840** | **652.286040** |

### Recovery execution decomposition

All values are seconds.

| Metric | Dataset | Average | Median |
|---|---|---:|---:|
| Preflight validation | 1,000 | 0.492812 | 0.420262 |
| Preflight validation | 10,000 | 7.682649 | 8.522402 |
| Preflight validation | 100,000 | 80.057766 | 83.849889 |
| Preflight validation | 500,000 | 180.199753 | 173.872105 |
| Simulation clone replay | 1,000 | 0.445410 | 0.403134 |
| Simulation clone replay | 10,000 | 4.808267 | 4.595346 |
| Simulation clone replay | 100,000 | 50.153725 | 38.277816 |
| Simulation clone replay | 500,000 | 128.812351 | 130.562236 |
| Live apply | 1,000 | 0.556187 | 0.535267 |
| Live apply | 10,000 | 10.436449 | 9.602125 |
| Live apply | 100,000 | 78.279473 | 52.153239 |
| Live apply | 500,000 | 210.283172 | 204.666725 |
| Commit | 1,000 | 0.023356 | 0.016573 |
| Commit | 10,000 | 0.135118 | 0.097323 |
| Commit | 100,000 | 0.172822 | 0.162361 |
| Commit | 500,000 | 1.683358 | 1.680261 |

### Memory and integrity

| Dataset | Median peak RSS | Median RSS growth | Rows checked | Runs committed | Runs verified | Errors |
|---:|---:|---:|---:|---:|---:|---:|
| 1,000 | 30.69 MB | 2.24 MB | 1,050 | 3/3 | 3/3 | 0 |
| 10,000 | 87.51 MB | 5.81 MB | 10,050 | 3/3 | 3/3 | 0 |
| 100,000 | 535.63 MB | 4.97 MB | 100,050 | 3/3 | 3/3 | 0 |
| 500,000 | 1,768.32 MB | 51.11 MB | 500,050 | 3/3 | 3/3 | 0 |

## Dataset size vs recovery duration

Using median total recovery duration:

| Inventory rows | Median total recovery duration | Change vs previous dataset |
|---:|---:|---:|
| 1,000 | 2.185059 s | baseline |
| 10,000 | 28.365067 s | 12.98× |
| 100,000 | 347.718108 s | 12.26× |
| 500,000 | 652.286040 s | 1.88× |

A 10× row increase from 1,000 to 10,000 raised median duration by about 13×. From 10,000 to 100,000 it again rose by about 12×. From 100,000 to 500,000 it rose by 1.88×, which is sublinear but still substantial in absolute terms: roughly 5 minutes 25 seconds longer.

The 100,000-row dataset showed the largest variance, with planning averaging 41.589 seconds versus a 13.943-second median. Medians are therefore used for the headline comparison.

## Bottleneck analysis

At 500,000 rows, the median total duration of 652.286 seconds decomposes approximately as:

- Preflight validation: 173.872 s (26.7%).
- Simulation clone replay: 130.562 s (20.0%).
- Live apply: 204.667 s (31.4%).
- Checksum verification: 63.026 s (9.7%).
- Snapshot/history/planning/commit and measurement overhead: the remainder.

The dominant costs are therefore preflight validation, simulation replay, and live apply. These scale with the number of recovery steps and per-row database work. Checksum verification is now materially smaller than the pre-optimization path but remains a measurable, linear component.

## Recommendations

1. Optimize preflight validation first: it is the largest single overhead at 10,000 and 500,000 rows and repeatedly inspects steps, schema, conflicts, and foreign keys.
2. Reduce simulation and apply round-trips further; both replay one compensation step per affected row and also create recovery history rows through triggers.
3. Keep checksum comparison streaming and avoid cross-database sample SQL; the previous path was orders of magnitude slower on realistic datasets.
4. Re-run this exact benchmark matrix after any recovery-engine optimization so improvements are evidence-based.
5. Treat memory as a scaling constraint: the 500,000-row run reached about 1.77 GB process high-water RSS on an 8 GB machine.

## Reproduction

```bash
python3 benchmarks/benchmark_recovery.py \
  --datasets 1000 10000 100000 500000 \
  --iterations 3 \
  --output benchmarks/benchmark_results.json
```

A single dataset can be generated independently with:

```bash
python3 benchmarks/generate_data.py --rows 100000 --db /tmp/tt-100k.db
```

A benchmark run is valid only when the JSON report contains no errors and every run reports `audit_status: committed` and `integrity_status: VERIFIED`.
