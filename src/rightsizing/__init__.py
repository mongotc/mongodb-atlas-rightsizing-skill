"""
MongoDB Atlas cluster rightsizing — evaluation and reporting.

Consumes the extraction.json produced by src/extraction/ (per-cluster metric
time-series + a small `config` block with tier / provisioned IOPS /
autoscaling) and produces a verdict per cluster:

  scale_up            — one or more scale-up thresholds crossed
  disk_iops_only      — only disk signals fired; fix with more IOPS / disk
  scale_down_candidate — comfortable under every scale-down bar (conservative)
  no_change           — no scale-up trigger crossed
  insufficient_data   — core metrics missing or too new a cluster
  not_supported       — shared / free / flex / serverless tier
  not_applicable      — mongos routers (informational only)

Threshold values live in thresholds.yaml (tunable). Atlas fact tables (tier
connection limits, shared-tier set) live in src/constants/tiers.py.

Per-cluster-shape evaluators, mirroring src/extraction/:
  evaluate_replicaset — dedicated replica set (M10+)
  evaluate_shard      — sharded cluster (per-shard + mongos routers)
  evaluate_search     — Atlas Search deployment (orthogonal to the mongod shape)
"""
