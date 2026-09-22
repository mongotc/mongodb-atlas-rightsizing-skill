# MongoDB Atlas Rightsizing Skill

An agent skill that produces data-backed rightsizing recommendations for MongoDB Atlas clusters
(scale up / change disk or IOPS only / scale down / no change), using hardware metrics from the
Atlas Admin API and, optionally, database-internal diagnostics. It is read-only: it never modifies
a cluster.

See [SKILL.md](SKILL.md) for the agent workflow and [references/](references/) for the decision
rules.

## Quick start

```bash
pip install -r requirements.txt
cp .env.example .env    # fill in ATLAS_CLIENT_ID / ATLAS_CLIENT_SECRET (or API key) and MONGODB_URI
set -a; . ./.env; set +a
python scripts/rightsizing.py --group-id "$ATLAS_GROUP_ID" --cluster Cluster0 --days 7 --out-dir ./rightsizing-report
```

Optional database diagnostics and merge:

```bash
python scripts/db_diagnostics.py --sample-interval 60 --out-dir ./rightsizing-report
python scripts/merge_verdict.py --rightsizing-report ./rightsizing-report/report.json --db-diagnostics ./rightsizing-report/db_diagnostics.json --out-dir ./rightsizing-report
```

## Layout

| Path | Purpose |
|---|---|
| `SKILL.md` | Skill definition and workflow for the agent |
| `scripts/rightsizing.py` | Atlas Admin API metrics → per-node evaluation → `report.md` / `report.json` |
| `scripts/db_diagnostics.py` | Optional `serverStatus` / `dbStats` / `collStats` snapshot |
| `scripts/merge_verdict.py` | Combines the two into `merged_report.md` / `merged_report.json` |
| `scripts/config.example.json` | Targets file for auditing several projects/clusters (`--config`) |
| `references/` | Metrics, thresholds and merge rules |
| `tests/` | Unit tests |

## Tests

Standard library `unittest`, no Atlas access needed (needs `requests` installed):

```bash
python -m unittest discover tests
```

## Requirements

Python 3.8+. `requests` for `rightsizing.py`; `pymongo` only for `db_diagnostics.py`.
