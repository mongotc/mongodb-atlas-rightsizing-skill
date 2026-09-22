---
name: mongodb-rightsizing
description: Generate MongoDB Atlas cluster rightsizing recommendations by pulling hardware metrics (CPU, memory, disk IOPS, disk space, disk latency, connections, WiredTiger cache) from the Atlas Admin API and comparing them against tier-appropriate thresholds. Use this skill whenever the user asks about Atlas cluster sizing, whether a cluster is over- or under-provisioned, cost optimization for Atlas clusters, scaling recommendations, "is my cluster too big/small", capacity planning, or wants a report on cluster hardware utilization. Also trigger for requests to audit multiple clusters/projects for sizing issues.
---

# MongoDB Atlas Rightsizing

Produces a data-backed recommendation (scale up / change disk or IOPS only / scale down / no
change) for one or more Atlas clusters, using real hardware metrics from the Atlas Admin API rather
than guesswork.

## Prerequisites

The user needs Atlas API credentials with at least **Project Read Only** access, set as
**environment variables** (the script does not accept secrets as flags, so they never land in shell
history or the process list):
- An Atlas **Service Account**: `ATLAS_CLIENT_ID` / `ATLAS_CLIENT_SECRET` (OAuth2), preferred, or
- A legacy **API key**: `ATLAS_PUBLIC_KEY` / `ATLAS_PRIVATE_KEY` (HTTP Digest)

`.env.example` shows the variables; copy it to `.env` (git-ignored) and source it. Never ask the
user to paste secrets into chat.

They also need the **Project (Group) ID**, found in the Atlas UI under Project Settings or via
`GET /api/atlas/v2/groups`.

If the user doesn't have these yet, point them to:
https://www.mongodb.com/docs/atlas/configure-api-access/

## Workflow

1. **Collect inputs** from the user:
   - Project ID (`groupId`)
   - Cluster name(s), or "all" to audit every cluster in the project
   - Lookback window (default: 7 days, long enough to smooth daily cycles). Offer 30 days if the
     user cares about monthly peaks (batch jobs, reporting). For spot-checking a live situation,
     `--hours N` (whole hours) uses 1-minute granularity up to 36 hours; it always reports low
     confidence and never replaces the 7-day audit for a sizing decision.
   - For several projects/clusters at once, write a targets file like `scripts/config.example.json`
     and pass `--config`.

2. **Run the script** (`--cluster` is optional; omit it to audit every cluster in the project):
   ```bash
   python scripts/rightsizing.py --group-id <groupId> --cluster <clusterName> --days 7 --out-dir ./rightsizing-report
   ```
   This writes `report.md` (human-readable) and `report.json` (structured) to `--out-dir`. Exit
   status 2 means at least one cluster hit an Atlas API error; the report marks it `error` and still
   covers the others.

3. **What the script does** (for each cluster):
   - Reads the cluster config (`GET /groups/{groupId}/clusters/{name}`): tier(s) across every
     region config, provisioned IOPS, and compute/storage auto-scaling settings.
   - Lists the project's processes (paginated) and keeps only this cluster's nodes, matched exactly
     on the hostnames in the cluster's connection string (so `prod` never picks up
     `prod-analytics`).
   - Fetches host and per-disk-partition measurements for **each node** (`granularity=PT1H`,
     `period=P{days}D`), for the metric set in `references/metrics.md`. API failures and rate limits
     are retried, then reported; they are never silently treated as "no data".
   - Evaluates **each node separately** against `references/thresholds.md` and judges the replica
     set (or shard) by its worst node, so a hot primary isn't averaged away by idle secondaries.
   - Classifies the result as **scale up**, **change disk / IOPS only**, **scale down candidate**,
     **no change**, or **insufficient data**, with a confidence level that accounts for window
     length, gaps in the data, and metrics sitting close to a trigger.

4. **Present the results**: show `report.md` inline (it's what the user actually wants to read),
   and mention `report.json` if they want to feed it into another system or diff runs over time.

5. **Caveats to state explicitly** (the report includes these; repeat them when summarizing):
   - This is a recommendation, not an autoscaling action; nothing is changed in Atlas.
   - Metrics reflect the lookback window only. Call out if it doesn't cover a known peak period
     (month-end batch, Black Friday, etc.) and suggest a longer `--days`.
   - **Never present "insufficient data" or low confidence as "the cluster is fine."** Low
     confidence usually means gaps in the data or values close to a trigger; say which.
   - If compute auto-scaling is on, a manual tier change may be overridden; the report says what to
     change instead (min/max instance size).
   - Sharded clusters: processes are grouped by `replicaSetName` (each shard and the config server
     is its own replica set), giving one verdict per shard plus an informational row for mongos
     routers. This hasn't been checked against a live sharded cluster yet: compare the shard
     breakdown with the Atlas UI the first time, and say so if you haven't. If shards have different
     provisioned IOPS, the IOPS check is skipped and the report says so.
   - Free/shared/flex tiers (M0/M2/M5/Flex) don't expose full hardware measurements and are
     reported as not supported.

## Optional: database-internal diagnostics (when the user has DB credentials)

The Atlas Admin API only sees OS/hardware metrics. It can tell you the box is under pressure, but
not *why*: a CPU spike from a missing index looks identical to genuine undersizing. If the user has
(or can get) a MongoDB user with `clusterMonitor` and read access, run `scripts/db_diagnostics.py`,
then `scripts/merge_verdict.py` to combine the two. That's what lets the report say "add an index"
instead of "buy a bigger cluster" when that's the real fix. Ask whether they have this access
before assuming Atlas-only; don't ask them to create new database users unless they want to.
**`merge_verdict.py` works with only the rightsizing report (clearly labeled Atlas-only); never
block on this step.**

```bash
# MONGODB_URI holds the connection string (see .env.example); don't pass it as a flag.
python scripts/db_diagnostics.py --sample-interval 60 --out-dir ./rightsizing-report
python scripts/merge_verdict.py --rightsizing-report ./rightsizing-report/report.json --db-diagnostics ./rightsizing-report/db_diagnostics.json --out-dir ./rightsizing-report
```

Omit `--db-diagnostics` entirely for Atlas-only users. If it's given but the file can't be read,
the merge stops with an error rather than quietly falling back.

`db_diagnostics.py` takes at least `--sample-interval` seconds (it samples `serverStatus()` twice to
compute rates); tell the user before starting it. It records which host it connected to, and the
merge only applies it to the replica set (or, via mongos, the cluster) it came from; a file from a
different cluster is rejected. Read `references/db-diagnostics.md` for the combination rules before
hand-tuning `merge_verdict.py`.

## Files

- `scripts/rightsizing.py`: pulls Atlas hardware metrics and produces the verdicts. Depends on `requests`.
- `scripts/db_diagnostics.py`: optional second data source (`serverStatus()`/`dbStats()`/`collStats()`
  over a direct connection). Depends on `pymongo`.
- `scripts/merge_verdict.py`: combines the two reports. Standard library only.
- `scripts/config.example.json`: targets file for `rightsizing.py --config` (several projects/clusters).
- `references/metrics.md`: the Atlas measurement names pulled and why each matters.
- `references/thresholds.md`: the decision rules and the tier reference table.
- `references/db-diagnostics.md`: how the two data sources are combined, including disagreements.
- `tests/`: unit tests (`python -m unittest discover tests`).

Read `references/thresholds.md` before hand-tuning thresholds for a user's risk tolerance (e.g. a
user who says "we never want to be CPU-bound" wants a lower scale-up trigger than the default).

## Handling common follow-ups

- **"Why is it recommending X?"**: read back the relevant rule from `references/thresholds.md` and
  the node's actual numbers from `report.json` (`nodes[].metric_summary`). Don't just restate the
  recommendation.
- **"What would the new tier cost?"**: the script doesn't fetch pricing (Atlas has no stable public
  pricing API). Point the user to the Atlas pricing calculator or their billing page instead of
  guessing.
- **"Apply this change"**: out of scope by design (read-only). If the user wants it automated,
  that's a different task (`PATCH /groups/{groupId}/clusters/{clusterName}`): flag that in-place
  tier changes trigger a rolling restart, and confirm explicitly before writing that code.
