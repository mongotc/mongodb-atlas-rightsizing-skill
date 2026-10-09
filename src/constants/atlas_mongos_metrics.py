# Metrics the Atlas /processes/{processId}/measurements endpoint returns
# (no m=) for a sharded-cluster routing/config process. The reference probe
# was run against a SHARD_MONGOS process on port 27016 (co-located with a
# SHARD_CONFIG_* on port 27017 under Atlas 8.0's embedded-config topology).
#
# Mirrors the structure of atlas_mongo_metrics.py: HARDWARE_METRICS covers
# host-level resource consumption, STATUS_METRICS covers process state.
#
# Additionally, mongos processes accept the Atlas Search measurements
# endpoint — /hosts/{processId}/fts/metrics/measurements — and return the
# standard FTS metric SCHEMA (dataPoints are typically empty since mongot
# runs on mongod hosts, not mongos). Those names/units live in
# atlas_search_metrics.py as the single source of truth and are re-exported
# below as FTS_HARDWARE_METRICS / FTS_STATUS_METRICS.
HARDWARE_METRICS = {
    # process CPU
    "PROCESS_CPU_USER":                           "PERCENT",
    "PROCESS_CPU_KERNEL":                         "PERCENT",
    "PROCESS_CPU_CHILDREN_USER":                  "PERCENT",
    "PROCESS_CPU_CHILDREN_KERNEL":                "PERCENT",
    "PROCESS_NORMALIZED_CPU_USER":                "PERCENT",
    "PROCESS_NORMALIZED_CPU_KERNEL":              "PERCENT",
    "PROCESS_NORMALIZED_CPU_CHILDREN_USER":       "PERCENT",
    "PROCESS_NORMALIZED_CPU_CHILDREN_KERNEL":     "PERCENT",
    "MAX_PROCESS_CPU_USER":                       "PERCENT",
    "MAX_PROCESS_CPU_KERNEL":                     "PERCENT",
    "MAX_PROCESS_CPU_CHILDREN_USER":              "PERCENT",
    "MAX_PROCESS_CPU_CHILDREN_KERNEL":            "PERCENT",
    "MAX_PROCESS_NORMALIZED_CPU_USER":            "PERCENT",
    "MAX_PROCESS_NORMALIZED_CPU_KERNEL":          "PERCENT",
    "MAX_PROCESS_NORMALIZED_CPU_CHILDREN_USER":   "PERCENT",
    "MAX_PROCESS_NORMALIZED_CPU_CHILDREN_KERNEL": "PERCENT",

    # process memory (NOTE: MEGABYTES)
    "MEMORY_RESIDENT": "MEGABYTES",
    "MEMORY_VIRTUAL":  "MEGABYTES",
    "MEMORY_MAPPED":   "MEGABYTES",

    # system CPU
    "SYSTEM_CPU_USER":        "PERCENT",
    "SYSTEM_CPU_KERNEL":      "PERCENT",
    "SYSTEM_CPU_NICE":        "PERCENT",
    "SYSTEM_CPU_IOWAIT":      "PERCENT",
    "SYSTEM_CPU_IRQ":         "PERCENT",
    "SYSTEM_CPU_SOFTIRQ":     "PERCENT",
    "SYSTEM_CPU_GUEST":       "PERCENT",
    "SYSTEM_CPU_STEAL":       "PERCENT",
    "MAX_SYSTEM_CPU_USER":    "PERCENT",
    "MAX_SYSTEM_CPU_KERNEL":  "PERCENT",
    "MAX_SYSTEM_CPU_NICE":    "PERCENT",
    "MAX_SYSTEM_CPU_IOWAIT":  "PERCENT",
    "MAX_SYSTEM_CPU_IRQ":     "PERCENT",
    "MAX_SYSTEM_CPU_SOFTIRQ": "PERCENT",
    "MAX_SYSTEM_CPU_GUEST":   "PERCENT",
    "MAX_SYSTEM_CPU_STEAL":   "PERCENT",

    # system normalized CPU (divided by core count)
    "SYSTEM_NORMALIZED_CPU_USER":        "PERCENT",
    "SYSTEM_NORMALIZED_CPU_KERNEL":      "PERCENT",
    "SYSTEM_NORMALIZED_CPU_NICE":        "PERCENT",
    "SYSTEM_NORMALIZED_CPU_IOWAIT":      "PERCENT",
    "SYSTEM_NORMALIZED_CPU_IRQ":         "PERCENT",
    "SYSTEM_NORMALIZED_CPU_SOFTIRQ":     "PERCENT",
    "SYSTEM_NORMALIZED_CPU_GUEST":       "PERCENT",
    "SYSTEM_NORMALIZED_CPU_STEAL":       "PERCENT",
    "MAX_SYSTEM_NORMALIZED_CPU_USER":    "PERCENT",
    "MAX_SYSTEM_NORMALIZED_CPU_KERNEL":  "PERCENT",
    "MAX_SYSTEM_NORMALIZED_CPU_NICE":    "PERCENT",
    "MAX_SYSTEM_NORMALIZED_CPU_IOWAIT":  "PERCENT",
    "MAX_SYSTEM_NORMALIZED_CPU_IRQ":     "PERCENT",
    "MAX_SYSTEM_NORMALIZED_CPU_SOFTIRQ": "PERCENT",
    "MAX_SYSTEM_NORMALIZED_CPU_GUEST":   "PERCENT",
    "MAX_SYSTEM_NORMALIZED_CPU_STEAL":   "PERCENT",

    # system memory (NOTE: KILOBYTES)
    "SYSTEM_MEMORY_USED":          "KILOBYTES",
    "SYSTEM_MEMORY_AVAILABLE":     "KILOBYTES",
    "SYSTEM_MEMORY_FREE":          "KILOBYTES",
    "SYSTEM_MEMORY_SHARED":        "KILOBYTES",
    "SYSTEM_MEMORY_CACHED":        "KILOBYTES",
    "SYSTEM_MEMORY_BUFFERS":       "KILOBYTES",
    "MAX_SYSTEM_MEMORY_USED":      "KILOBYTES",
    "MAX_SYSTEM_MEMORY_AVAILABLE": "KILOBYTES",
    "MAX_SYSTEM_MEMORY_FREE":      "KILOBYTES",
    "MAX_SYSTEM_MEMORY_SHARED":    "KILOBYTES",
    "MAX_SYSTEM_MEMORY_CACHED":    "KILOBYTES",
    "MAX_SYSTEM_MEMORY_BUFFERS":   "KILOBYTES",

    # system network
    "SYSTEM_NETWORK_IN":      "BYTES_PER_SECOND",
    "SYSTEM_NETWORK_OUT":     "BYTES_PER_SECOND",
    "MAX_SYSTEM_NETWORK_IN":  "BYTES_PER_SECOND",
    "MAX_SYSTEM_NETWORK_OUT": "BYTES_PER_SECOND",

    # swap
    "SWAP_USAGE_USED":     "KILOBYTES",
    "SWAP_USAGE_FREE":     "KILOBYTES",
    "MAX_SWAP_USAGE_USED": "KILOBYTES",
    "MAX_SWAP_USAGE_FREE": "KILOBYTES",
    "SWAP_IO_IN":          "SCALAR_PER_SECOND",
    "SWAP_IO_OUT":         "SCALAR_PER_SECOND",
    "MAX_SWAP_IO_IN":      "SCALAR_PER_SECOND",
    "MAX_SWAP_IO_OUT":     "SCALAR_PER_SECOND",
}


STATUS_METRICS = {
    # asserts
    "ASSERT_REGULAR": "SCALAR_PER_SECOND",
    "ASSERT_WARNING": "SCALAR_PER_SECOND",
    "ASSERT_MSG":     "SCALAR_PER_SECOND",
    "ASSERT_USER":    "SCALAR_PER_SECOND",

    # connections / cursors
    "CONNECTIONS":                                   "SCALAR",
    "CONNECTIONS_ESTABLISHMENT_RATE_LIMIT_REJECTED": "SCALAR_PER_SECOND",
    "CURSORS_TOTAL_OPEN":                            "SCALAR",
    "CURSORS_TOTAL_TIMED_OUT":                       "SCALAR_PER_SECOND",

    # network at the process layer
    "NETWORK_BYTES_IN":     "BYTES_PER_SECOND",
    "NETWORK_BYTES_OUT":    "BYTES_PER_SECOND",
    "NETWORK_NUM_REQUESTS": "SCALAR_PER_SECOND",

    # opcounters
    "OPCOUNTER_CMD":         "SCALAR_PER_SECOND",
    "OPCOUNTER_QUERY":       "SCALAR_PER_SECOND",
    "OPCOUNTER_UPDATE":      "SCALAR_PER_SECOND",
    "OPCOUNTER_DELETE":      "SCALAR_PER_SECOND",
    "OPCOUNTER_TTL_DELETED": "SCALAR_PER_SECOND",
    "OPCOUNTER_GETMORE":     "SCALAR_PER_SECOND",
    "OPCOUNTER_INSERT":      "SCALAR_PER_SECOND",

    # operation throttling / spills / page faults
    "OPERATIONS_QUERIES_KILLED":                "SCALAR_PER_SECOND",
    "OPERATION_THROTTLING_REJECTED_OPERATIONS": "SCALAR_PER_SECOND",
    "QUERY_SPILL_TO_DISK_DURING_SORT":          "SCALAR_PER_SECOND",
    "EXTRA_INFO_PAGE_FAULTS":                   "SCALAR_PER_SECOND",
}


# Full catalog, metric name -> units. Includes FTS metrics (served by the
# separate /hosts/{procId}/fts/metrics/measurements endpoint) so unit lookup
# works regardless of which endpoint produced the data point.
ALL_METRICS = {
    **HARDWARE_METRICS,
    **STATUS_METRICS,
}
