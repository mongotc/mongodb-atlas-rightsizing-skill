# Changelog

## 2026-09-22: code review fixes

Verdict correctness
- API failures are no longer swallowed. Failed measurement or disk calls raise instead of silently
  dropping metrics; 429 and 5xx responses are retried with backoff (honoring `Retry-After`). A
  cluster that still fails is reported as `error` without stopping the rest of the audit, and the
  script exits with status 2.
- A missing core metric (CPU user/kernel, memory used/free, disk space) now gives
  `insufficient_data` instead of "no change, confidence: high".
- Confidence now accounts for sample coverage (< 90% of expected samples = low), metrics close to a
  trigger, and missing core metrics, as `thresholds.md` always described.
- Processes are matched to a cluster on exact host prefix and domain from its connection string, so
  `prod` no longer picks up `prod-analytics` or `prod2`, and a replica set is no longer mistaken for
  a sharded cluster. Process, cluster and disk listings are paginated.
- Every node is evaluated separately and the replica set / shard is judged by its worst node, so a
  hot primary can't be averaged away by idle secondaries. Disk partitions are evaluated separately.

Rules now matching the docs
- CPU is user + kernel. IOPS are read + write against the combined provisioned budget. Free memory
  is judged on its low end (p5), per sample.
- CPU, IOPS and disk-space triggers must be sustained (≥ 3 of the last 7 days).
- New verdict: change disk / IOPS only, when every trigger is a disk signal.
- Scale-down also requires IOPS < 50% of provisioned, low disk latency, full coverage and nothing
  close to a trigger.
- Compute and storage auto-scaling settings are read and reported.
- Tiers and IOPS are read from every region config; analytics / read-only nodes on a different tier
  are noted.
- Connection limits cover M10–M700 plus R-series and NVMe tiers, from the Atlas limits page, stored
  as the range the docs give (M80: 64000–96000). Unknown tiers skip the check with a note.
- The "rising eviction trend" wording was removed from `thresholds.md`; it was never implemented.

merge_verdict.py / db_diagnostics.py
- An unreadable `--db-diagnostics` path is an error, not a silent Atlas-only fallback.
- Total data + index size is no longer called the working set or treated as decisive; it only
  agrees with a memory scale-up when Atlas shows page-fault pressure.
- Scan efficiency uses documents examined vs documents returned, plus collection scans, instead of
  index keys vs `opcounters.query` (which excluded aggregations).
- The disk finding needs real cache churn (cache ≥ 80% full with reads and evictions), not just any
  page read.
- Findings are labeled agrees / disagrees / likely root cause / context; confidence overrides are
  applied; an index-first recommendation leads the section when indicated.
- Diagnostics record which host they came from and only apply to matching report rows; rows that
  weren't evaluated get no findings.
- The eviction rate now sums `modified pages evicted` + `unmodified pages evicted`. The old
  `pages evicted` key doesn't exist on MongoDB 8.0 (found on a live M10); it read as 0 before.
- Missing counters are recorded as null, not 0; failed collStats calls are listed; connecting via
  mongos explains the missing cache fields.

Other
- Timestamps are valid UTC (`...Z`, not `...+00:00Z`).
- `--days` / `--hours` take whole numbers.
- Secrets come from environment variables only (`MONGODB_URI` for db_diagnostics; `--uri` still
  works with a warning).
- `rightsizing.py --config` reads the targets file for multi-project audits.
- `report.json` rows carry structured `triggers`, per-node summaries, coverage and notes.
- Sample `report/` with a real project ID removed from the repo; unit tests, README and
  requirements added.

## Earlier history

- Replaced the WiredTiger ticket-count trigger with queue depth (false positives on MongoDB 7.0+).
- Renamed "disk utilization" to disk space used (it measures capacity, not I/O) and added disk
  latency as the I/O signal.
- Added the connections trigger (documented but not implemented before).
- Added `insufficient_data` for clusters with no metrics in the window.
- Added `db_diagnostics.py` and `merge_verdict.py`.
