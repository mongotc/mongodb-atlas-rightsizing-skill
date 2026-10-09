# Hardware metrics: host-level resource consumption — system + mongod-process
# CPU, memory, network, swap. Served by
#     /groups/{groupId}/processes/{processId}/measurements
# Units confirmed against a live Atlas response; several are not SI-byte
# (SYSTEM_MEMORY_* is KILOBYTES, MEMORY_RESIDENT/VIRTUAL/MAPPED is MEGABYTES).
HARDWARE_METRICS = {
    # mongod process CPU
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

    # mongod process memory
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
    "MAX_SYSTEM_CPU_IOWAIT": "PERCENT",
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

    # system memory (NOTE: KILOBYTES, not bytes)
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


# Status metrics: mongod operational state — connections, cursors, opcounters,
# locks, tickets, cache, asserts, page faults. Same endpoint as HARDWARE_METRICS.
# CACHE_*_RATIO and CACHE_PRESSURE_PERCENTAGE arrive on a 0-100 scale, not 0-1.
# Lock / ticket / cache / op-execution metrics only come back when explicitly
# requested via m=; they aren't in the default (no-m=) response.
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

    # network at the mongod layer
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

    # tickets / locks (m=-only)
    "TICKETS_AVAILABLE_READS":           "SCALAR",
    "TICKETS_AVAILABLE_WRITE":           "SCALAR",
    "GLOBAL_LOCK_CURRENT_QUEUE_READERS": "SCALAR",
    "GLOBAL_LOCK_CURRENT_QUEUE_WRITERS": "SCALAR",

    # op execution time (m=-only)
    "OP_EXECUTION_TIME_READS":  "MILLISECONDS",
    "OP_EXECUTION_TIME_WRITES": "MILLISECONDS",

    # WiredTiger cache (m=-only; *_RATIO / *_PERCENTAGE arrive as 0-100)
    "CACHE_BYTES_READ_INTO":     "BYTES_PER_SECOND",
    "CACHE_BYTES_WRITTEN_FROM":  "BYTES_PER_SECOND",
    "CACHE_FILL_RATIO":          "PERCENT",
    "DIRTY_FILL_RATIO":          "PERCENT",
    "CACHE_PRESSURE_PERCENTAGE": "PERCENT",
}


# Disk partition metrics: scoped to one data-volume partition on a mongod host.
# Served by a different endpoint
#     /groups/{groupId}/processes/{processId}/disks/{partitionName}/measurements
# NOT /processes/{processId}/measurements — those will reject these names.
DISK_METRICS = {
    "DISK_PARTITION_IOPS_READ":          "SCALAR_PER_SECOND",
    "DISK_PARTITION_IOPS_WRITE":         "SCALAR_PER_SECOND",
    "DISK_PARTITION_SPACE_USED":         "BYTES",
    "DISK_PARTITION_SPACE_FREE":         "BYTES",
    "DISK_PARTITION_SPACE_PERCENT_USED": "PERCENT",
    "DISK_PARTITION_LATENCY_READ":       "MILLISECONDS",
    "DISK_PARTITION_LATENCY_WRITE":      "MILLISECONDS",
    "DISK_PARTITION_THROUGHPUT_READ":    "BYTES_PER_SECOND",
    "DISK_PARTITION_THROUGHPUT_WRITE":   "BYTES_PER_SECOND",
}


# The /processes/{procId}/measurements endpoint also returns FTS_* metrics
# (mongot process / disk, attributed to the mongod host). Those names and
# units live in atlas_search_metrics.py.HARDWARE_METRICS to keep a single
# source of truth for Search-side definitions.


# Full catalog, metric name -> units, across all four namespaces. Handy for
# unit lookup when rendering charts without caring which endpoint served it.
ALL_METRICS = {**HARDWARE_METRICS, **STATUS_METRICS, **DISK_METRICS}
