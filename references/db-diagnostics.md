# Combining Atlas hardware metrics with database-internal diagnostics

`rightsizing.py` answers "is the hardware under pressure." `db_diagnostics.py` answers "why, and is
more hardware actually the fix." Run both when database credentials are available: Atlas metrics
alone can only recommend bigger or smaller, while db diagnostics let the skill recommend *index this
collection* instead of a tier change, which is often cheaper and correct.

`scripts/merge_verdict.py` implements the rules on this page; keep the table below and its constants
(`HIGH_EXAMINED_RATIO`, `WT_CACHE_MODERATE_PCT`, `WT_CACHE_FULL_PCT`, `DB_CONNECTIONS_ELEVATED_PCT`)
in sync. The merge reads the structured `triggers` list each row of `report.json` carries, not the
wording of the reason text.

## Signals and what they mean together

Each finding is labeled with how it relates to the Atlas verdict: **AGREES**, **DISAGREES**,
**LIKELY ROOT CAUSE** (explains the Atlas signal and points at a different fix), or **CONTEXT**.

| Atlas trigger | DB-internal signal | Label | Combined read |
|---|---|---|---|
| CPU | documents examined : returned > 10, and collection scans happening (or not reported) | LIKELY ROOT CAUSE | Missing/poor indexes, not undersized compute. The report leads with an index review (Performance Advisor or `explain()`) before any tier bump. |
| CPU | examined : returned > 10 but no collection scans | CONTEXT | Fits aggregations or large index range scans more than missing indexes; check Performance Advisor before assuming either. |
| CPU | examined : returned ≤ 10 | AGREES | Queries look efficient; the load is probably real and a compute bump is reasonable. |
| Memory / cache fill / page faults | total data + index size > WT cache, **and** Atlas page-fault trigger | AGREES | Consistent with the hot set not fitting in cache. |
| Memory / cache fill | total data + index size > WT cache, no page-fault trigger | CONTEXT | Normal; doesn't show the hot set doesn't fit. Judge on the Atlas evidence alone. |
| Memory / cache fill / page faults | everything fits in the WT cache and it's < 60% full | DISAGREES (confidence → low) | The pressure Atlas sees probably isn't WiredTiger (another process, OS page cache, a short spike). Don't recommend a memory-driven scale-up from Atlas alone. |
| Connections | snapshot > 60% in use | AGREES | Real connection pressure, often an app connection-pooling problem as much as a tier problem. Mention both fixes. |
| Connections | snapshot ≤ 60% in use | DISAGREES (confidence → at most medium) | Different windows or a resolved spike; check the Atlas connections chart. |
| none | snapshot > 60% in use | DISAGREES | The snapshot may have caught a spike the Atlas window smoothed out. |
| Disk IOPS or read latency | WT cache ≥ 80% full while pages are read in and evicted | LIKELY ROOT CAUSE | Read I/O is likely cache misses; more RAM (or a smaller hot set) may help more than more IOPS. |
| Write latency only | – | CONTEXT | Cache misses don't explain write-side pressure; look at write volume and `DIRTY_FILL_RATIO`. |

### Why "total data" isn't the working set

`dbStats` gives the total data and index size, which is only an **upper bound** on the working set
(the part that's actually hot). Most healthy clusters hold far more data than cache. An earlier
version treated "total data > cache" as decisive, high-confidence proof of a memory-driven scale-up.
The real M10 it was tuned on shows why that's wrong: data was ~18x its 512 MB cache, yet Atlas showed
page faults p95 of 0.32/sec and no cache pressure, meaning the hot set fit fine. So the size
comparison only **agrees** with a memory scale-up when Atlas also shows page-fault pressure.

### Why documents examined, not keys examined

`metrics.queryExecutor.scanned` counts index keys examined, which is normal and healthy.
`scannedObjects` counts documents examined, which is what balloons without a good index. It's
compared against `metrics.document.returned` rather than `opcounters.query`, because
`opcounters.query` leaves out aggregations and would make aggregation-heavy workloads look like they
examine documents for "no queries". `metrics.queryExecutor.collectionScans.total` (when the server
reports it) is required before blaming indexes.

## Rule: disagreement gets surfaced, not silently resolved

If Atlas and the db diagnostics disagree, the report shows both numbers, says so explicitly with a
plausible reason (different windows, a resolved spike, too short a sample), and lowers the merged
confidence where the table says so. Never quietly prefer one source.

## Rule: schema/query fixes are cheaper; surface them first

When a scan-efficiency problem shows up alongside a hardware-pressure signal, the merged report
leads with the index/query fix and frames the tier change as the fallback. Scaling up hides an
indexing problem and costs money every month; fixing the index is often a one-time change.

## Rule: a snapshot only applies to where it came from

`db_diagnostics.json` records the host(s) it connected to (`source`). The merge applies it only to
report rows whose nodes include one of those hosts; connected through mongos, it applies to every
shard of that cluster, with a warning that one connection point can hide a hot shard. A file whose
hosts match no node in the report is rejected (override with `--allow-host-mismatch` only if the
hostnames are aliases of the same nodes). Rows with no evaluated verdict (mongos, errors,
insufficient data, not supported) never get findings. Older files without `source` are applied to
every evaluated row, with a warning.

## Practical notes on running `db_diagnostics.py`

- `serverStatus()` counters are cumulative, so the script samples twice, `--sample-interval`
  seconds apart. Use at least 60s; 300s+ gives cleaner rates for bursty workloads. Tell the user
  before starting it.
- Needs `clusterMonitor` (for `serverStatus`) and `read` on the inspected databases (for
  `dbStats`/`collStats`). Don't ask for more.
- Pass the connection string in `MONGODB_URI`, not `--uri`, so the password stays out of shell
  history and the process list.
- Anything the server didn't report is recorded as `null`, never 0, and failed `dbStats`/`collStats`
  calls are listed under `errors`.
- Through mongos, `serverStatus` has no `wiredTiger` section, so cache fields are `null` and a note
  says so. Connect to a shard member for cache stats, and to individual shard primaries if a
  specific shard is suspected.
- This complements `rightsizing.py`; it doesn't replace it.
