# Metrics pulled from the Atlas Admin API

Two endpoints, because Atlas splits host-level and disk-level measurements:

- **Host-level**: `GET /api/atlas/v2/groups/{groupId}/processes/{processId}/measurements`
- **Disk-level**: `GET /api/atlas/v2/groups/{groupId}/processes/{processId}/disks/{partitionName}/measurements`
  (asking the host-level endpoint for a disk metric 404s with `INVALID_METRIC_NAME`; they're
  separate resources.)

Query params: `granularity=PT1H&period=P{N}D&m=<metric>`, with `m` repeated for each metric so one
call covers the whole list. `--hours` runs use `granularity=PT1M` up to 36 hours (Atlas keeps
1-minute data for roughly 38 hours) and `PT1H` beyond that. Windows are whole days or hours.

> Measurement names are an Atlas API enum that occasionally changes. If a name is wrong, Atlas
> rejects the whole request (400/404) and `rightsizing.py` stops with that error for the cluster
> (marked `error` in the report, exit status 2) rather than dropping the metric. Rate limits (429)
> and transient 5xx errors are retried with backoff first. Cross-check against the current
> `MeasurementView` `name` enum in the Atlas Admin API reference when adding a metric.

## Host-level metrics (`HOST_METRICS` in `rightsizing.py`)

| Metric | Why it matters for rightsizing |
|---|---|
| `SYSTEM_NORMALIZED_CPU_USER` / `SYSTEM_NORMALIZED_CPU_KERNEL` | CPU normalized to the tier's cores, so it's comparable across tiers. Summed per timestamp for the CPU trigger (user + kernel). Both are **core** metrics: if either is missing, the verdict is `insufficient_data`. |
| `SYSTEM_MEMORY_USED` / `SYSTEM_MEMORY_FREE` | Free share of memory, `free / (free + used)` per sample, judged on its low end (p5). A weaker signal than it looks (Linux uses spare RAM for page cache); see `EXTRA_INFO_PAGE_FAULTS`. Core metrics. |
| `CONNECTIONS` | Compared against the tier's per-node limit (`TIER_MAX_CONNECTIONS`). |
| `TICKETS_AVAILABLE_READS` / `TICKETS_AVAILABLE_WRITE` | WiredTiger concurrency tickets, **context only** (see `thresholds.md` "Concurrency queuing"). Atlas naming quirk: `READS` plural, `WRITE` singular. |
| `GLOBAL_LOCK_CURRENT_QUEUE_READERS` / `WRITERS` | The concurrency trigger: operations actually waiting for a slot. |
| `OP_EXECUTION_TIME_READS` / `WRITES` | Context only; quoted next to a queuing trigger. |
| `EXTRA_INFO_PAGE_FAULTS` | Per second. A more direct sign of an undersized WT cache than free memory. |
| `CACHE_BYTES_READ_INTO` | Bytes/sec, context only; quoted next to a page-fault trigger. |
| `CACHE_FILL_RATIO` / `DIRTY_FILL_RATIO` | WT eviction pressure, already 0–100 (`units: PERCENT`). See `thresholds.md` "WiredTiger eviction thresholds". |
| `SYSTEM_NORMALIZED_CPU_IOWAIT` | Context only; quoted next to a disk-latency trigger when above 5%. |

## Disk-level metrics (`DISK_METRICS` in `rightsizing.py`), per partition

| Metric | Why it matters for rightsizing |
|---|---|
| `DISK_PARTITION_IOPS_READ` / `DISK_PARTITION_IOPS_WRITE` | Summed per timestamp and compared against the cluster's *provisioned* IOPS (a combined budget). |
| `DISK_PARTITION_SPACE_PERCENT_USED` | Disk **capacity** consumed, NOT I/O saturation (`DISK_PARTITION_UTILIZATION` doesn't exist; it 404s). Core metric. |
| `DISK_PARTITION_SPACE_USED` / `DISK_PARTITION_SPACE_FREE` | Raw values behind the percentage, for context. |
| `DISK_PARTITION_LATENCY_READ` / `WRITE` | The "is the disk keeping up" signal (ms per op). |
| `DISK_PARTITION_THROUGHPUT_READ` / `WRITE` | Context only; Atlas exposes no provisioned-throughput ceiling to compare against. |

## Which processes belong to a cluster

`GET /groups/{groupId}/processes` (paginated) returns every process in the project. A process is
kept when its `userAlias`, `hostname` or `id` has the same `<prefix>-shard-NN-NN` / `-config-NN-NN`
prefix and domain as a host in the cluster's `connectionStrings.standard`. If the cluster response
has no connection string, the prefix must equal the cluster name exactly. The old substring /
starts-with match pulled `prod-analytics` and `prod2` into `prod`.

Processes are then grouped by `replicaSetName` (one group per shard and for the config server);
processes without one, or with `typeName` `SHARD_MONGOS`, are mongos routers and are reported for
visibility only. This grouping hasn't been checked against a live sharded cluster yet.
