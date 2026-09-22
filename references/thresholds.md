# Rightsizing decision rules

These are defaults tuned for "don't cry wolf, but don't miss a real problem." Adjust per user risk
tolerance: a user optimizing hard for cost will want lower scale-down bars; a user who says latency
or incidents matter most wants lower scale-up bars and more headroom than these defaults leave.

The constants live at the top of `scripts/rightsizing.py`; keep them and this page in sync.

## How a cluster is evaluated

- **Every node is evaluated on its own**, then the replica set (or shard) is judged by its worst
  node. Pooling primary and secondary samples would let two idle secondaries hide a primary pinned
  at 90% CPU.
- Each disk partition is evaluated on its own too.
- Percentiles are taken over the node's own samples for the whole window.

## Scale UP triggers (any one is enough; every one that fired is listed)

| Signal | Threshold | Sustained? |
|---|---|---|
| Normalized CPU (user + kernel) | p95 > 80% | yes |
| Free memory | p5 < 10% of (free + used), i.e. low for at least 5% of the window | no |
| Disk IOPS (read + write) | p95 > 90% of provisioned IOPS | yes |
| Disk space used | p95 > 90% of capacity (NOT I/O saturation) | yes |
| Disk latency (read or write) | p95 > 15ms (heuristic) | no |
| Connections | p95 > 80% of the tier's per-node limit | no |
| Concurrency queuing | read or write queue depth p95 > 0 (NOT ticket count) | no |
| Page faults | p95 > 1.0/sec (heuristic) | no |
| Cache fill ratio | p95 > 80% (WT `eviction_target`) | no |
| Dirty fill ratio | p95 > 5% (WT `eviction_dirty_target`) | no |

**Sustained** means the threshold is also breached on at least 3 of the last 7 UTC days (a day
counts when that day's own p95 is over the threshold). Shorter windows need proportionally fewer
days, minimum 1. A p95 over the threshold that isn't sustained is reported as "close to a trigger",
not as a trigger.

**Disk-only verdict:** if every trigger that fired is a disk signal (IOPS, disk space, disk
latency), the verdict is **change disk / IOPS only**: check whether more IOPS or a bigger disk
resolves it before recommending a compute tier jump. Dedicated tiers support independently
provisioned IOPS on most cloud providers.

If several signals fire together (e.g. CPU + IOPS), say so explicitly: it changes the fix (compute
bump vs. IOPS bump vs. both).

### Memory

Free memory is a low-is-bad metric, so it's judged on the **low end** of the window (p5), computed
per sample as `free / (free + used)`. An earlier version compared the *p95* of free memory against
10%, which only fired if memory was nearly exhausted 95% of the time. Low free memory is still a
weak signal on its own (Linux uses spare RAM for page cache); page faults and cache fill are more
direct.

### Disk space vs. disk I/O

`DISK_PARTITION_SPACE_PERCENT_USED` is disk **capacity** consumed (it matches
`used / (used + free) * 100` exactly), not I/O busy time. The I/O signal is
`DISK_PARTITION_LATENCY_READ`/`WRITE` (ms per op): it needs no ceiling to be meaningful, since
rising per-op latency directly means queries are slower. The 15ms cutoff is a heuristic, not from
MongoDB/Atlas documentation; tune it to your workload. Throughput (bytes/sec) and CPU iowait are
quoted as context next to a latency trigger; Atlas exposes no provisioned-throughput ceiling to turn
throughput into a trigger.

### IOPS

Provisioned IOPS is a combined budget, so read and write IOPS are summed per timestamp before
comparing. If the cluster config doesn't report `diskIOPS`, the check is skipped and the report says
so (never silently).

### Connections

Compared against `TIER_MAX_CONNECTIONS` in `rightsizing.py`, from "Connection Limits and Cluster
Tier" at https://www.mongodb.com/docs/atlas/reference/atlas-limits/ (checked 2026-09-22). That page
has several tables (by cloud provider / cluster class) that disagree for some tiers: M40 is 4000 or
6000, M80 is 64000 or 96000. The check uses the lower value, so it errs toward flagging, and the
report quotes the range. R-series (low-CPU) and `_NVME` tiers use their M-number's entry. M10's 1500
was also confirmed on a live cluster (`serverStatus().connections`: current + available = 1500).
Tiers not in the table skip the check with a note.

### Concurrency queuing (not WiredTiger ticket count)

The old trigger on low `TICKETS_AVAILABLE_READS`/`WRITE` was removed: since MongoDB 7.0 the ticket
pool is resized dynamically, so a low "available" count can just mean a light workload. On this
skill's MongoDB 8.0 test cluster, tickets available held at p50=4 all week while
`GLOBAL_LOCK_CURRENT_QUEUE_READERS` stayed at max 0: nothing ever waited.

The trigger is queue depth (`GLOBAL_LOCK_CURRENT_QUEUE_READERS`/`WRITERS`): operations actually
waiting for a slot, which means the same thing on any version. `p95 > 0` ignores a single blip but
catches contention in more than 5% of samples. At hourly granularity each sample is an hourly
average, so this is sensitive; confirm with `OP_EXECUTION_TIME_*` (quoted as context). Ticket counts
are still pulled for context.

### WiredTiger cache pressure (page faults)

`EXTRA_INFO_PAGE_FAULTS` (per second) is a more direct sign of an undersized cache than free memory:
it means MongoDB is going to disk for pages that should be cached. The `p95 > 1.0/sec` cutoff is a
deliberately sensitive heuristic, not from documentation (Atlas storage is SSD-backed, so each
fault is cheap). Treat a lone page-fault trigger as weaker evidence than CPU/IOPS triggers, and look
at `CACHE_BYTES_READ_INTO` (quoted as context) before recommending a RAM-focused bump.

### WiredTiger eviction thresholds (cache fill / dirty fill ratio)

WiredTiger's eviction thresholds, as percentages of the *configured* cache (not host RAM):

| Parameter | Default | Behavior |
|---|---|---|
| `eviction_target` | 80% | Background eviction threads start bringing usage down |
| `eviction_trigger` | 95% | **Pressured**: application threads are recruited to evict, stalling reads/writes |
| `eviction_dirty_target` | 5% | Background eviction starts on dirty (not yet checkpointed) pages |
| `eviction_dirty_trigger` | 20% | **Pressured**: application threads evict dirty pages, which needs a disk write |

The script triggers on the `_target` values (80% / 5%) to flag sustained background eviction
before it becomes application-thread stalling. If that's too noisy for a workload, move to the
`_trigger` values (95% / 20%). `CACHE_FILL_RATIO` and `DIRTY_FILL_RATIO` are already 0–100; don't
multiply by 100.

## Scale DOWN candidate (ALL of the following, on EVERY node; deliberately conservative)

- CPU (user + kernel) p95 < 20%
- Free memory p5 > 40% (consistently, not on average)
- On every disk partition: space used p95 < 50%, IOPS (read + write) p95 < 50% of provisioned (when
  known), read and write latency p95 < 5ms
- Page faults p95 < 0.5/sec, cache fill p95 < 50%, dirty fill p95 < 2%
- No queuing at all (queue depth max = 0)
- Connections p95 < 30% of the tier's limit
- At least 7 days of data, ≥ 90% sample coverage (no significant gaps), and nothing close to a
  scale-up trigger

Present scale-down candidates with a confidence caveat and ask whether the window captures peak
traffic (month-end, seasonal, campaigns) before treating it as a strong recommendation. If compute
auto-scaling with scale-down is on, Atlas should downsize by itself; the report says to lower
`minInstanceSize` instead of changing the tier manually.

## No change

No trigger fired, and the scale-down bar isn't met. Say so plainly; "currently well-matched" is a
valid result. If some metric is **close to a trigger** (p95 within 10% of it, or over it but not
sustained), the report lists it and confidence is low.

**This is different from insufficient data.** The verdict is `insufficient_data` (confidence low)
when a node returned no metrics at all, or any **core metric** (CPU user, CPU kernel, memory used,
memory free, disk space used) is missing. Before this rule, a cluster created ~30 minutes before a
7-day audit returned an empty table and still reported "no change, confidence: high". Never
summarize an empty or partial metrics table as "no change".

## Confidence levels

- **High**: ≥ 7 days, ≥ 90% sample coverage, no missing core metrics; for a scale-up, at least two
  different triggers agree; for no-change / scale-down, nothing close to a trigger.
- **Medium**: 3–6 day window, or a scale-up with a single trigger.
- **Low**: < 3 days, sample coverage < 90% (gaps from restarts, a cluster younger than the window),
  missing core metrics, or (for no-change / scale-down) a metric close to a trigger. Say which, and
  suggest re-running with a longer window before acting.

Coverage is the lowest, across nodes, of samples received ÷ samples expected (24 per day at PT1H;
60 per hour at PT1M) for the core metrics.

## Auto-scaling

The cluster's compute and storage auto-scaling settings are read from every region config and
turned into notes: a manual tier change on an auto-scaling cluster may be overridden, so the report
points at `minInstanceSize` / `maxInstanceSize` (or enabling scale-down) instead. With storage
auto-scaling on, a disk-space trigger may resolve itself.

## M-tier reference (vCPU / RAM), for describing headroom between tiers

Confirm current specs in the Atlas UI or the `GET /clusters/{name}` response before quoting numbers,
since Atlas revises tier specs.

| Tier | vCPU (approx) | RAM (approx) |
|---|---|---|
| M10 | 2 | 2 GB |
| M20 | 2 | 4 GB |
| M30 | 2 | 8 GB |
| M40 | 4 | 16 GB |
| M50 | 8 | 32 GB |
| M60 | 16 | 64 GB |
| M80 | 32 | 128 GB |
| M140/M200/M300 | 64+ | 192 GB+ |
