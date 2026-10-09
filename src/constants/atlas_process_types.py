# Unique process typeName values returned by
#     GET /api/atlas/v2/groups/{groupId}/processes
# on the ApiHostView_Atlas.typeName enum. Used to distinguish mongod vs mongos
# vs config-server processes when iterating cluster topology.
#
# SHARD_CONFIG_PRIMARY / SHARD_CONFIG_SECONDARY are observed in live Atlas
# responses (MongoDB 8.0 sharded clusters) but are NOT in the published
# OpenAPI enum — add here when you encounter new values.
PROCESS_TYPES = (
    "REPLICA_PRIMARY",
    "REPLICA_SECONDARY",
    "RECOVERING",
    "SHARD_MONGOS",
    "SHARD_CONFIG",
    "SHARD_CONFIG_PRIMARY",
    "SHARD_CONFIG_SECONDARY",
    "SHARD_STANDALONE",
    "SHARD_PRIMARY",
    "SHARD_SECONDARY",
    "NO_DATA",
)

# Grouped by role for convenient membership checks.
MONGOS_TYPES = ("SHARD_MONGOS",)

CONFIG_TYPES = (
    "SHARD_CONFIG",
    "SHARD_CONFIG_PRIMARY",
    "SHARD_CONFIG_SECONDARY",
)

MONGOD_DATA_TYPES = (
    "REPLICA_PRIMARY",
    "REPLICA_SECONDARY",
    "RECOVERING",
    "SHARD_STANDALONE",
    "SHARD_PRIMARY",
    "SHARD_SECONDARY",
)
