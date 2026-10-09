# Hardware metrics: per-process CPU, memory, disk. Served by the standard
# /hosts/{procId}/fts/metrics/measurements endpoint. These are what Atlas
# attributes to the mongot process on each Search Node.
HARDWARE_METRICS = {
    "FTS_DISK_USAGE":                   "BYTES",
    "FTS_PROCESS_CPU_USER":             "PERCENT",
    "FTS_PROCESS_CPU_KERNEL":           "PERCENT",
    "FTS_PROCESS_NORMALIZED_CPU_USER":  "PERCENT",
    "FTS_PROCESS_NORMALIZED_CPU_KERNEL": "PERCENT",
    "FTS_PROCESS_RESIDENT_MEMORY":      "BYTES",
    "FTS_PROCESS_VIRTUAL_MEMORY":       "BYTES",
    "FTS_PROCESS_SHARED_MEMORY":        "BYTES",
}


# Status metrics: JVM heap + page faults. Served by the same measurements
# endpoint as HARDWARE_METRICS. JVM values are in MEGABYTES, not bytes.
STATUS_METRICS = {
    "JVM_CURRENT_MEMORY": "MEGABYTES",
    "JVM_MAX_MEMORY":     "MEGABYTES",
    "PAGE_FAULTS":        "SCALAR_PER_SECOND",
}


# Per-index metrics: Search query/replication statistics scoped to a single
# Search index. Served by a different endpoint
#     /hosts/{procId}/fts/metrics/indexes/{database}/{collection}/measurements
#     /hosts/{procId}/fts/metrics/indexes/{database}/{collection}/{indexName}/measurements
# NOT /hosts/{procId}/fts/metrics/measurements — those will reject these names.
INDEX_METRICS = {
    "REPLICATION_LAG":            "MILLISECONDS",
    "NUMBER_OF_SUCCESS_QUERIES":  "SCALAR_PER_SECOND",
    "NUMBER_OF_ERROR_QUERIES":    "SCALAR_PER_SECOND",
    "TOTAL_NUMBER_OF_QUERIES":    "SCALAR_PER_SECOND",
    "NUMBER_OF_GETMORE_COMMANDS": "SCALAR_PER_SECOND",
    "NUMBER_OF_INSERTS":          "SCALAR_PER_SECOND",
    "NUMBER_OF_UPDATES":          "SCALAR_PER_SECOND",
    "NUMBER_OF_DELETES":          "SCALAR_PER_SECOND",
    "INDEX_SIZE_ON_DISK":         "BYTES",
    "NUMBER_OF_INDEX_FIELDS":     "SCALAR",
}


# Full catalog, metric name -> units, across all three namespaces. Handy for
# unit lookup when rendering charts without caring which endpoint served it.
ALL_METRICS = {**HARDWARE_METRICS, **STATUS_METRICS, **INDEX_METRICS}
