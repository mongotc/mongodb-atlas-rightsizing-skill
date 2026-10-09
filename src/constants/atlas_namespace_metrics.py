# Per-collection metrics: query latency / op counters scoped to a single
# collection. Served by a different endpoint
#     /groups/{groupId}/collStats/metrics                                        (list names)
#     /groups/{groupId}/clusters/{clusterName}/{clusterView}/{databaseName}/{collectionName}/collStats/measurements
#     /groups/{groupId}/processes/{processId}/{databaseName}/{collectionName}/collStats/measurements
# NOT /processes/{processId}/measurements — those will reject these names.
COLLECTION_METRICS = {
    "READS_OPS":                 "SCALAR_PER_SECOND",
    "READS_LATENCY":             "MICROSECONDS_PER_SECOND",
    "AVERAGE_READS_LATENCY":     "MICROSECONDS",
    "READS_P50_VALUE":           "MICROSECONDS",
    "READS_P95_VALUE":           "MICROSECONDS",
    "READS_P99_VALUE":           "MICROSECONDS",
    "WRITES_OPS":                "SCALAR_PER_SECOND",
    "WRITES_LATENCY":            "MICROSECONDS_PER_SECOND",
    "AVERAGE_WRITES_LATENCY":    "MICROSECONDS",
    "WRITES_P50_VALUE":          "MICROSECONDS",
    "WRITES_P95_VALUE":          "MICROSECONDS",
    "WRITES_P99_VALUE":          "MICROSECONDS",
    "COMMANDS_OPS":              "SCALAR_PER_SECOND",
    "COMMANDS_LATENCY":          "MICROSECONDS_PER_SECOND",
    "AVERAGE_COMMANDS_LATENCY":  "MICROSECONDS",
    "COMMANDS_P50_VALUE":        "MICROSECONDS",
    "COMMANDS_P95_VALUE":        "MICROSECONDS",
    "COMMANDS_P99_VALUE":        "MICROSECONDS",
    "TOTAL_OPS":                 "SCALAR_PER_SECOND",
    "TOTAL_LATENCY":             "MICROSECONDS_PER_SECOND",
    "AVERAGE_TOTAL_OPS_LATENCY": "MICROSECONDS",
    "TOTAL_OPS_P50_VALUE":       "MICROSECONDS",
    "TOTAL_OPS_P95_VALUE":       "MICROSECONDS",
    "TOTAL_OPS_P99_VALUE":       "MICROSECONDS",
}

ALL_METRICS = {**COLLECTION_METRICS}
