"""
MongoDB Atlas cluster rightsizing — evaluation and reporting.

Consumes the extraction.json produced by src/extraction/ (per-cluster metric
time-series + a small `config` block with tier / provisioned IOPS /
autoscaling) and produces a verdict per cluster:

  scale_up    — one or more scale-up thresholds crossed
  scale_down  — comfortable under every scale-down bar (requires 7+ day window)
  no_change   — anything else (insufficient data, shared tier, mongos, borderline)

Detail that used to be its own verdict (disk-only triggers, insufficient data,
free/shared tier, mongos routers) now lives in the `reasons` field.

Threshold values live in src/config.yaml (tunable). Atlas fact tables (tier
connection limits, shared-tier set) live in src/constants/tiers.py.

Per-cluster-shape evaluators, mirroring src/extraction/:
  evaluate_replicaset — dedicated replica set (M10+)
  evaluate_shard      — sharded cluster (per-shard + mongos routers)
  evaluate_search     — Atlas Search deployment (orthogonal to the mongod shape)
"""
