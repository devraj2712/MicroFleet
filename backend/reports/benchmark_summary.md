# MicroFleet — Empirical Evaluation & Baseline Benchmark Report

**Evaluation Date:** 2026-10-24T08:10:27.059182+00:00
**Random Seed:** `42`

## 1. Quantitative Performance Comparison Table

| Scale (Orders) | Batches | Solo Dist (km) | Greedy Dist (km) | MicroFleet (km) | Dist Saved vs Solo | Dist Saved vs Greedy | Compute (ms) | On-Time Rate |
| :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| **10** | 3 | 73.7 | 41.3 | **38.4** | **+48.0%** | +7.2% | 1783.7 ms | 100% |
| **20** | 6 | 146.9 | 117.7 | **82.8** | **+43.6%** | +29.6% | 1801.7 ms | 100% |
| **30** | 13 | 209.5 | 146.5 | **99.8** | **+52.4%** | +31.9% | 3057.5 ms | 100% |

## 2. Algorithmic Insights & Academic Defense

- **Fuzzy Urgency Layer**: Prioritizes tight SLA margins and long customer waiting times, preventing starvation of high-priority orders.
- **Genetic Algorithm Batching**: Combines geographically proximate orders while strictly enforcing $20\text{ kg}$ vehicle limits and separating incompatible cargo (medical goods vs perishables).
- **Ant Colony Optimization (ACO)**: Synthesizes precedence-compliant pickup-and-delivery tours, avoiding unnecessary crisscrossing.
- **Adaptive Dispatch Policy**: Distributes batches to avoid rider bottlenecking and schedules conflicting multi-batch dispatches cleanly.
