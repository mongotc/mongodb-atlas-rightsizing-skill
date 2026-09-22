import os
import sys
from datetime import datetime, timedelta

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts"))

START = datetime(2026, 9, 15)


def series(values, step_minutes=60, start=START):
    """[(iso timestamp, value)] at a fixed step, like an Atlas measurements response."""
    return [((start + timedelta(minutes=i * step_minutes)).strftime("%Y-%m-%dT%H:%M:%SZ"), v)
            for i, v in enumerate(values)]


def week(value, n=168):
    """A full 7-day hourly series. value may be a constant or a function of the hour index."""
    return series([value(i) if callable(value) else value for i in range(n)])


def healthy_node(n=168, **overrides):
    """A quiet, fully-observed node that should qualify as a scale-down candidate."""
    host = {
        "SYSTEM_NORMALIZED_CPU_USER": week(8, n),
        "SYSTEM_NORMALIZED_CPU_KERNEL": week(2, n),
        "SYSTEM_MEMORY_USED": week(500, n),
        "SYSTEM_MEMORY_FREE": week(1500, n),
        "CONNECTIONS": week(40, n),
        "GLOBAL_LOCK_CURRENT_QUEUE_READERS": week(0, n),
        "GLOBAL_LOCK_CURRENT_QUEUE_WRITERS": week(0, n),
        "EXTRA_INFO_PAGE_FAULTS": week(0.1, n),
        "CACHE_FILL_RATIO": week(30, n),
        "DIRTY_FILL_RATIO": week(1, n),
    }
    disk = {
        "DISK_PARTITION_SPACE_PERCENT_USED": week(20, n),
        "DISK_PARTITION_IOPS_READ": week(100, n),
        "DISK_PARTITION_IOPS_WRITE": week(100, n),
        "DISK_PARTITION_LATENCY_READ": week(1, n),
        "DISK_PARTITION_LATENCY_WRITE": week(1, n),
    }
    for k, v in overrides.items():
        (disk if k.startswith("DISK_") else host)[k] = v
    for k in [k for k, v in list(host.items()) + list(disk.items()) if v is None]:
        host.pop(k, None)
        disk.pop(k, None)
    return {"host": host, "disks": {"data": disk}}


def week_window():
    import rightsizing
    return rightsizing.build_window(days=7)


def ctx(window=None, provisioned_iops=3000, max_connections=(1500, 1500)):
    return {"window": window or week_window(), "provisioned_iops": provisioned_iops,
            "max_connections": max_connections}


def node(data, label="n0", role="REPLICA_PRIMARY", hosts=("cluster0-shard-00-00.abcde.mongodb.net",)):
    return {"label": label, "role": role, "hosts": list(hosts), "data": data}
