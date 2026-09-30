# Atlas Search node rightsizing decision rules

These are conservative defaults for dedicated Atlas Search Nodes (`mongot`), 
not database nodes. They are proposed audit rules, not MongoDB product limits 
or an implementation already present in `scripts/rightsizing.py`. 

Tune them to the application's search latency and freshness SLO, peak periods, 
index growth, and tolerance for cost versus risk. Search Nodes are sized 
separately from `mongod`; Atlas provisions them per replica set or per shard. 
[Deployment options](https://www.mongodb.com/docs/atlas/atlas-search/about/deployment-options/)

## How a deployment is evaluated

* Evaluate each Search Node separately; use the worst node in each shard or 
replica set for the verdict. Do not average an overloaded node into idle peers. 
Evaluate disk usage and indexed-data growth per node; each Search Node must 
have room for its own index copy. 
[Search Node sizing considerations](https://docs.google.com/document/d/1cgQv6XS7pUIypV_WPDpkh7Bw96mucysjG3WIDLRFxMk)

* Use a representative 7-day window by default, with at least 90% sample 
coverage. Compute p95 for high-is-bad metrics and p5 for low-is-bad metrics 
over each node's samples. For daily persistence, require a daily p95 breach 
on at least 3 of the last 7 UTC days (proportionally fewer in shorter windows,
minimum 1). This persistence convention is borrowed from the supplied 
database-node template; it is an audit heuristic, not an Atlas alert setting.

* Compare search latency, failed-query rate, QPS, and index freshness against 
the application's baseline or SLO; there is no universal QPS or latency cutoff. 
Pair Search metrics with application timing because end-to-end results also 
depend on `mongod` document lookup and downstream pipeline work. 
[Search metrics](https://www.mongodb.com/docs/atlas/review-atlas-search-metrics/) · 

[Deployment options](https://www.mongodb.com/docs/atlas/atlas-search/about/deployment-options/)

## Scale UP / OUT triggers (any one is enough; list every signal that fired)

| Signal | Proposed threshold | Sustained? | First interpretation |
|---|---|---|---|
| Search Normalized Process CPU | p95 > 80% | Yes | CPU-bound: investigate query, indexing, and merges; add nodes for aggregate query concurrency, or choose a larger tier for per-node work. |
| Search Process Throttling | > 0 for at least 5 minutes, or nonzero p95 at coarser sampling | No | Admission queue is overloaded; check query bursts and latency, then reduce load or increase CPU capacity. |
| Search Node disk space used | ≥ 80% on any node; ≥ 85% is urgent | No | Preserve headroom before replication pauses at 90%; increase per-node storage capacity/tier or reduce index footprint. |
| Search Max Replication Lag | Growing across the window and breaching the freshness SLO, or ≥ 30% of the current `mongod` oplog window | Yes for trend/SLO; no if near oplog exhaustion | Investigate write bursts, indexing capacity, oplog window, and paused replication. |
| Search process OOM, stopped replication, or insufficient rebuild space alert | Any occurrence | No | Immediate incident/mitigation, not an ordinary percentile-based recommendation. |
| Search-query p95/p99 latency or error rate | Breaches the application's SLO during comparable traffic | Yes for latency; incident for errors | Confirm the Search stage is the bottleneck before buying capacity. |
| Search JVM heap / host memory and page faults | No standalone universal percentage trigger | Context only | Escalate if heap or resident use approaches its *actual* limit and faults/I/O correlate with slower queries or OOM. |

The CPU and 80% disk cutoffs and the 30%-of-oplog lag warning above are *operational heuristics*. A recent PS observability engagement used >70% and >80% CPU as warning/critical, ≥70% and ≥80% disk as warning/critical, and 30%/50% of the oplog window for lag; use workload-specific calibration rather than presenting those as Atlas defaults. 


### CPU and throttling

Use **Search Normalized Process CPU** (0–100% across cores), not raw Search Process CPU, which can exceed 100% on multicore nodes. Search Process Throttling is a rate per second of queue-threshold exceedances, not a queue-depth gauge. Atlas's overloaded-process alert fires when that rate is > 0 for 5 minutes; a sustained nonzero value means incoming work exceeds admission capacity. At hourly granularity, any nonzero sample warrants investigation, but cannot establish an exact five-minute duration. 

* [Search metrics](https://www.mongodb.com/docs/atlas/review-atlas-search-metrics/)
* [Alert conditions](https://www.mongodb.com/docs/atlas/reference/alert-conditions/)
* [Fix MongoDB Search Issues](https://www.mongodb.com/docs/atlas/reference/alert-resolutions/atlas-search-alerts/)

### Disk and index footprint

Use actual Search Node **disk utilization**, not `Search Index Size / disk size` as if they were interchangeable. Search Disk Space Used includes indexes, diagnostic data, and logs; reserve space for growth and rebuilds. Atlas warns at ≥85% disk utilization, pauses `mongot` replication at 90%, and resumes below 85%. Its sizing guidance also calls out 20% local-SSD overhead for index operations. Adding nodes increases query capacity but does not by itself make an oversized copy of the index fit on a smaller per-node disk. Check tier capacity and available headroom before changes. 

* [Search metrics](https://www.mongodb.com/docs/atlas/review-atlas-search-metrics/)
* [Search alert resolution](https://www.mongodb.com/docs/atlas/reference/alert-resolutions/atlas-search-alerts/)
* [Deployment options](https://www.mongodb.com/docs/atlas/atlas-search/about/deployment-options/)

### Freshness, errors, and memory

`Search Max Replication Lag` is an approximate **millisecond** lag behind `mongod`'s oplog, not database secondary replication lag. If it approaches the oplog window, incremental sync can be lost and a full index rebuild may follow; stale results can continue during rebuild. Investigate write rate and oplog sizing as well as Search capacity. Report the configured oplog window; if unknown, mark the percentage test unavailable rather than assume 24 hours. [Search metrics](https://www.mongodb.com/docs/atlas/review-atlas-search-metrics/) · [Search alert resolution](https://www.mongodb.com/docs/atlas/reference/alert-resolutions/atlas-search-alerts/)

Do not equate low free OS memory with an undersized Search tier: the filesystem cache is useful for Lucene indexes. Track JVM heap against the JVM maximum when available, process resident memory against node RAM, and page faults alongside query latency and disk I/O. For vector indexes, memory/working-set requirements can differ materially from lexical Search; validate against the actual index and workload. Search Query Status supplies counts by status, not an application SLO. [Search metrics](https://www.mongodb.com/docs/atlas/review-atlas-search-metrics/) · [Deployment options](https://www.mongodb.com/docs/atlas/atlas-search/about/deployment-options/)

## Choose the remedy, not just the verdict

* **CPU/throttling with high aggregate QPS:** optimize expensive queries or add Search Nodes for throughput, preserving at least two per shard. Re-test at peak traffic and with one node unavailable. Atlas permits 2–32 Search Nodes and distributes queries across available nodes. [Deployment options](https://www.mongodb.com/docs/atlas/atlas-search/about/deployment-options/)
* **Per-query latency, indexing pressure, memory pressure, or per-node disk pressure:** inspect query and index design, then consider a larger or different Search tier; adding replicas does not reduce the size of each index copy. For large indexes with moderate query load, compare storage-optimized tiers where available. [Deployment options](https://www.mongodb.com/docs/atlas/atlas-search/about/deployment-options/) · [Sizing Search Nodes](https://www.mongodb.com/company/blog/technical/the-art-and-science-of-sizing-search-nodes)
* **Lag without Search saturation:** check `mongod` write bursts and oplog window first. **Disk + lag** is more urgent because disk pressure can pause Search replication. Report combined causes explicitly. [Search alert resolution](https://www.mongodb.com/docs/atlas/reference/alert-resolutions/atlas-search-alerts/)

## Scale DOWN candidate (ALL must hold)

* Every node: normalized Search CPU p95 < 25%; no sustained throttling; no OOM or disk/replication alerts; no search latency, error-rate, or freshness SLO breach.
* Every node: disk usage p95 < 50%, with projected index growth, logs, and rebuild overhead fitting on the proposed smaller tier. Memory working set and actual index footprint must also fit the candidate tier with headroom; low CPU alone is insufficient.
* At least 7 representative days and ≥90% coverage; projected normal *and one-node-failure* load on the remaining nodes stays below the proposed CPU and memory limits. Never reduce below two Search Nodes per shard. These scale-down bars are deliberately conservative audit heuristics, not guaranteed safe operating limits. [Search Node sizing considerations](https://docs.google.com/document/d/1cgQv6XS7pUIypV_WPDpkh7Bw96mucysjG3WIDLRFxMk) · [Deployment options](https://www.mongodb.com/docs/atlas/atlas-search/about/deployment-options/)

If the window excludes seasonal peaks, bulk indexing, index rebuilds, or a likely node failure, present a *candidate* rather than a firm reduction. Changing a Search tier or node count can initiate index rebuild/copy activity; confirm migration behavior, disk headroom, and the operational window before executing. Do not apply database-tier compute autoscaling assumptions to dedicated Search Nodes. [Deployment options](https://www.mongodb.com/docs/atlas/atlas-search/about/deployment-options/)

## No change and insufficient data

**No change:** no scale-up trigger fires, and the conservative scale-down bar is not met. List any near misses (within 10% of a proposed numeric trigger, over a trigger without persistence, or a worsening SLO trend).

**Insufficient data:** a node has no Search metrics, or core inputs (normalized Search CPU, Search disk utilization/capacity, throttling, and lag) are missing. Missing application latency/SLO, oplog window, memory limit, or proposed-tier specification blocks decisions relying on those inputs; label each skipped check. Do not convert missing metrics to zero or report an empty table as healthy. Atlas only provides Search metrics when an active Search index exists; pausing/resuming a cluster can reset its Search metrics history. [Search metrics](https://www.mongodb.com/docs/atlas/review-atlas-search-metrics/)

## Confidence levels

* **High:** ≥7 representative days, ≥90% coverage on every node, all core checks available; for scale-up, at least two independent pressure signals or one documented incident alert; for no-change/scale-down, no near misses and candidate-tier/failure projections verified.
* **Medium:** 3–6 days, or a single corroborated but non-incident pressure signal.
* **Low:** <3 days, <90% coverage, missing core checks, unrepresentative peaks, or close-to-trigger results. State why and request a longer or more representative window before acting.

Coverage is the minimum across Search Nodes and core metrics of received samples divided by samples expected at the chosen granularity, excluding periods when the deployment did not yet exist. These confidence rules are proposed audit conventions, not Atlas-native verdicts.

## Scope note

This file describes decision rules only; it does **not** claim `scripts/rightsizing.py` currently collects these metrics or implements these Search Node rules. Before wiring it into automation, verify the API/Datadog metric names, units, labels, current tier specifications, and actual Search deployment configuration. Search metrics and hardware metrics are available on the Atlas Search Nodes tab; the Atlas–Datadog integration also exposes throttling, lag, and JVM current/max memory. [Search metrics](https://www.mongodb.com/docs/atlas/review-atlas-search-metrics/) · [Datadog integration](https://www.mongodb.com/docs/atlas/tutorial/datadog-integration/)
