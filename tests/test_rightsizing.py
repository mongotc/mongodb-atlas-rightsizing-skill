import unittest

from helpers import ctx, healthy_node, node, series, week

import rightsizing as rs


class EvaluateGroupTests(unittest.TestCase):
    def evaluate(self, *datas, **ctx_kwargs):
        nodes = [node(d, label=f"n{i}") for i, d in enumerate(datas)]
        return rs.evaluate_group(nodes, ctx(**ctx_kwargs))

    def test_quiet_fully_observed_week_is_scale_down_candidate(self):
        r = self.evaluate(healthy_node(), healthy_node(), healthy_node())
        self.assertEqual(r["verdict"], "scale_down_candidate")
        self.assertEqual(r["confidence"], "high")

    def test_no_data_at_all_is_insufficient_data(self):
        # A cluster created ~30 minutes before a 7-day audit returned nothing at all.
        r = self.evaluate({"host": {}, "disks": {}})
        self.assertEqual((r["verdict"], r["confidence"]), ("insufficient_data", "low"))

    def test_no_processes_is_insufficient_data(self):
        r = rs.evaluate_group([], ctx())
        self.assertEqual(r["verdict"], "insufficient_data")

    def test_missing_core_metric_is_insufficient_data_not_confident_no_change(self):
        r = self.evaluate(healthy_node(SYSTEM_NORMALIZED_CPU_USER=None, CACHE_FILL_RATIO=week(60)))
        self.assertEqual((r["verdict"], r["confidence"]), ("insufficient_data", "low"))
        self.assertTrue(any("SYSTEM_NORMALIZED_CPU_USER" in n for n in r["notes"]))

    def test_gaps_in_data_give_low_confidence(self):
        # The committed M10 report: ~115 of 168 hourly samples, cache fill p95 78.57.
        r = self.evaluate(healthy_node(n=115, CACHE_FILL_RATIO=week(60, 115)))
        self.assertEqual(r["verdict"], "no_change")
        self.assertEqual(r["confidence"], "low")
        self.assertLess(r["coverage"], rs.MIN_COVERAGE)

    def test_near_threshold_gives_low_confidence_and_blocks_scale_down(self):
        r = self.evaluate(healthy_node(CACHE_FILL_RATIO=week(78.57), DIRTY_FILL_RATIO=week(4.52)))
        self.assertEqual((r["verdict"], r["confidence"]), ("no_change", "low"))
        self.assertEqual(len(r["borderline"]), 2)

    def test_hot_primary_is_not_averaged_away_by_idle_secondaries(self):
        primary = healthy_node(SYSTEM_NORMALIZED_CPU_USER=week(85), SYSTEM_NORMALIZED_CPU_KERNEL=week(5))
        r = self.evaluate(primary, healthy_node(), healthy_node())
        self.assertEqual(r["verdict"], "scale_up")
        self.assertIn("cpu", r["triggers"])
        self.assertTrue(r["reasons"][0].startswith("n0:"))

    def test_cpu_counts_user_plus_kernel(self):
        r = self.evaluate(healthy_node(SYSTEM_NORMALIZED_CPU_USER=week(70), SYSTEM_NORMALIZED_CPU_KERNEL=week(15)))
        self.assertIn("cpu", r["triggers"])

    def test_cpu_spike_on_one_day_is_borderline_not_sustained(self):
        spike = week(lambda h: 95 if h < 24 else 10)
        r = self.evaluate(healthy_node(SYSTEM_NORMALIZED_CPU_USER=spike))
        self.assertNotIn("cpu", r["triggers"])
        self.assertTrue(any("sustained" in b for b in r["borderline"]))

    def test_cpu_high_on_three_days_triggers(self):
        hot = week(lambda h: 95 if h < 72 else 10)
        r = self.evaluate(healthy_node(SYSTEM_NORMALIZED_CPU_USER=hot))
        self.assertIn("cpu", r["triggers"])

    def test_low_free_memory_most_of_the_time_triggers(self):
        # 5% free for 90% of the window: the old "free p95 < 10%" rule missed this.
        free = week(lambda h: 950 if h % 10 == 0 else 50)
        used = week(lambda h: 50 if h % 10 == 0 else 950)
        r = self.evaluate(healthy_node(SYSTEM_MEMORY_FREE=free, SYSTEM_MEMORY_USED=used))
        self.assertIn("memory", r["triggers"])

    def test_iops_are_summed_across_read_and_write(self):
        r = self.evaluate(healthy_node(DISK_PARTITION_IOPS_READ=week(1500), DISK_PARTITION_IOPS_WRITE=week(1400)))
        self.assertIn("iops", r["triggers"])
        self.assertEqual(r["verdict"], "disk_iops_only")

    def test_unknown_provisioned_iops_is_noted_on_scale_down(self):
        r = self.evaluate(healthy_node(), provisioned_iops=None)
        self.assertEqual(r["verdict"], "scale_down_candidate")
        self.assertTrue(any("IOPS headroom was not checked" in n for n in r["notes"]))

    def test_disk_space_only_is_disk_iops_only_verdict(self):
        r = self.evaluate(healthy_node(DISK_PARTITION_SPACE_PERCENT_USED=week(95)))
        self.assertEqual(r["verdict"], "disk_iops_only")

    def test_low_ticket_count_without_queueing_does_not_trigger(self):
        # MongoDB 8.0 test cluster: tickets available p50=4 all week, queue always 0.
        r = self.evaluate(healthy_node(TICKETS_AVAILABLE_READS=week(4)))
        self.assertEqual(r["triggers"], [])

    def test_real_queueing_triggers(self):
        r = self.evaluate(healthy_node(GLOBAL_LOCK_CURRENT_QUEUE_READERS=week(lambda h: 3 if h % 5 == 0 else 0)))
        self.assertIn("queue_read", r["triggers"])

    def test_connections_use_tier_limit(self):
        r = self.evaluate(healthy_node(CONNECTIONS=week(1300)))
        self.assertIn("connections", r["triggers"])

    def test_single_trigger_scale_up_is_medium_two_is_high(self):
        one = self.evaluate(healthy_node(CACHE_FILL_RATIO=week(90)))
        two = self.evaluate(healthy_node(CACHE_FILL_RATIO=week(90), DIRTY_FILL_RATIO=week(10)))
        self.assertEqual((one["verdict"], one["confidence"]), ("scale_up", "medium"))
        self.assertEqual((two["verdict"], two["confidence"]), ("scale_up", "high"))

    def test_short_window_is_never_scale_down_or_high(self):
        window = rs.build_window(hours=2)
        quiet = healthy_node()
        for group in (quiet["host"], quiet["disks"]["data"]):
            for k in group:
                group[k] = series([group[k][0][1]] * 120, step_minutes=1)
        r = rs.evaluate_group([node(quiet)], ctx(window=window))
        self.assertEqual((r["verdict"], r["confidence"]), ("no_change", "low"))


class TopologyTests(unittest.TestCase):
    CFG = {"connectionStrings": {"standard": (
        "mongodb://cluster0-shard-00-00.abcde.mongodb.net:27017,"
        "cluster0-shard-00-01.abcde.mongodb.net:27017/?ssl=true&replicaSet=atlas-xyz-shard-0")}}

    def proc(self, alias, rs_name="atlas-xyz-shard-0", type_name="REPLICA_SECONDARY"):
        return {"id": alias + ":27017", "userAlias": alias, "hostname": alias, "port": 27017,
                "replicaSetName": rs_name, "typeName": type_name}

    def test_similar_cluster_names_do_not_match(self):
        keys = rs.cluster_host_keys(self.CFG)
        mine = self.proc("cluster0-shard-00-02.abcde.mongodb.net")
        other = self.proc("cluster01-shard-00-00.abcde.mongodb.net")
        other_project = self.proc("cluster0-shard-00-00.zzzzz.mongodb.net")
        self.assertTrue(rs.process_matches(mine, keys, "Cluster0"))
        self.assertFalse(rs.process_matches(other, keys, "Cluster0"))
        self.assertFalse(rs.process_matches(other_project, keys, "Cluster0"))

    def test_fallback_uses_exact_prefix(self):
        self.assertTrue(rs.process_matches(self.proc("prod-shard-00-00.a.mongodb.net"), set(), "prod"))
        self.assertFalse(rs.process_matches(self.proc("prod-analytics-shard-00-00.a.mongodb.net"), set(), "prod"))
        self.assertFalse(rs.process_matches(self.proc("prod2-shard-00-00.a.mongodb.net"), set(), "prod"))

    def test_grouping_by_replica_set_and_routers(self):
        procs = [self.proc("c-shard-00-00.a.net", "rs0"), self.proc("c-shard-01-00.a.net", "rs1"),
                 self.proc("c-shard-00-00.a.net", None, "SHARD_MONGOS")]
        groups, routers = rs.group_processes_by_replica_set(procs)
        self.assertEqual(sorted(groups), ["rs0", "rs1"])
        self.assertEqual(len(routers), 1)

    def test_tier_info_reads_every_region_and_autoscaling(self):
        cfg = {"replicationSpecs": [{"regionConfigs": [
            {"electableSpecs": {"instanceSize": "M30", "diskIOPS": 3000},
             "autoScaling": {"compute": {"enabled": True, "scaleDownEnabled": False,
                                         "minInstanceSize": "M30", "maxInstanceSize": "M50"}}},
            {"electableSpecs": {"instanceSize": "M30", "diskIOPS": 3000},
             "analyticsSpecs": {"instanceSize": "M40", "nodeCount": 1}},
        ]}]}
        tiers, iops, autoscaling, notes = rs.tier_info(cfg)
        self.assertEqual((tiers, iops), (["M30"], [3000]))
        self.assertTrue(autoscaling["compute"]["enabled"])
        self.assertTrue(any("analytics" in n for n in notes))
        down = rs.autoscaling_notes(autoscaling, "scale_down_candidate", set())
        self.assertIn("scale-down is disabled", down[0])

    def test_connection_limits_cover_r_and_nvme_tiers(self):
        self.assertEqual(rs.TIER_MAX_CONNECTIONS[rs.normalize_tier("R40")], (4000, 6000))
        self.assertEqual(rs.TIER_MAX_CONNECTIONS[rs.normalize_tier("M40_NVME")], (4000, 6000))
        self.assertEqual(rs.TIER_MAX_CONNECTIONS[rs.normalize_tier("M80")], (64000, 96000))
        self.assertIn("M200", rs.TIER_MAX_CONNECTIONS)


class FakeResponse:
    def __init__(self, status, body=None, headers=None):
        self.status_code, self._body, self.headers = status, body or {}, headers or {}
        self.ok = 200 <= status < 300
        self.text = str(self._body)

    def json(self):
        return self._body


class FakeSession:
    def __init__(self, responses):
        self.responses, self.headers, self.auth, self.calls = list(responses), {}, None, []

    def get(self, url, params=None, timeout=None):
        self.calls.append((url, params))
        return self.responses.pop(0)

    def post(self, url, **kwargs):
        return FakeResponse(200, {"access_token": "t", "expires_in": 3600})


class AtlasClientTests(unittest.TestCase):
    ENV = {"ATLAS_PUBLIC_KEY": "pub", "ATLAS_PRIVATE_KEY": "priv"}

    def client(self, responses, env=None):
        sleeps = []
        c = rs.AtlasClient(session=FakeSession(responses), sleep=sleeps.append, env=env or self.ENV)
        return c, sleeps

    def test_retries_rate_limit_then_succeeds(self):
        c, sleeps = self.client([FakeResponse(429, headers={"Retry-After": "2"}), FakeResponse(200, {"ok": 1})])
        self.assertEqual(c.get("/x"), {"ok": 1})
        self.assertEqual(sleeps, [2.0])

    def test_bad_request_raises_instead_of_returning_empty(self):
        c, _ = self.client([FakeResponse(400, {"errorCode": "INVALID_METRIC_NAME"})])
        with self.assertRaises(rs.AtlasAPIError):
            c.get("/x")

    def test_gives_up_after_max_retries(self):
        c, _ = self.client([FakeResponse(503)] * 6)
        with self.assertRaises(rs.AtlasAPIError):
            c.get("/x")

    def test_pagination_follows_pages(self):
        page1 = FakeResponse(200, {"results": [1, 2], "totalCount": 3})
        page2 = FakeResponse(200, {"results": [3], "totalCount": 3})
        c, _ = self.client([page1, page2])
        self.assertEqual(c.get_all("/x", items_per_page=2), [1, 2, 3])

    def test_oauth_token_refreshed_on_401(self):
        c, _ = self.client([FakeResponse(401), FakeResponse(200, {"ok": 1})],
                           env={"ATLAS_CLIENT_ID": "id", "ATLAS_CLIENT_SECRET": "secret"})
        self.assertEqual(c.get("/x"), {"ok": 1})

    def test_missing_credentials(self):
        with self.assertRaises(rs.AtlasAPIError):
            rs.AtlasClient(session=FakeSession([]), env={})


class FakeAtlas:
    """Serves canned responses for evaluate_cluster()."""

    def __init__(self, cluster_cfg, metrics_by_process):
        self.cfg, self.metrics = cluster_cfg, metrics_by_process

    def get(self, path, params=None):
        if path.endswith("/measurements"):
            pid = path.split("/processes/")[1].split("/")[0]
            data = self.metrics[pid]
            wanted = [v for k, v in params if k == "m"]
            source = data["disks"]["data"] if "/disks/" in path else data["host"]
            return {"measurements": [
                {"name": name, "dataPoints": [{"timestamp": ts, "value": v} for ts, v in pts]}
                for name, pts in source.items() if name in wanted]}
        return self.cfg

    def get_all(self, path, params=None):
        return [{"partitionName": "data"}] if path.endswith("/disks") else []


class EvaluateClusterTests(unittest.TestCase):
    CFG = {
        "name": "Cluster0",
        "connectionStrings": {"standard": "mongodb://cluster0-shard-00-00.abcde.mongodb.net:27016/?ssl=true"},
        "replicationSpecs": [{"regionConfigs": [{"electableSpecs": {"instanceSize": "M10", "diskIOPS": 3000}}]}],
    }

    def proc(self, alias, rs_name, type_name, port=27017):
        return {"id": f"{alias}:{port}", "userAlias": alias, "hostname": alias, "port": port,
                "replicaSetName": rs_name, "typeName": type_name}

    def test_sharded_cluster_gets_per_shard_verdicts_and_router_row(self):
        procs = [
            self.proc("cluster0-shard-00-00.abcde.mongodb.net", "atlas-x-shard-0", "SHARD_PRIMARY"),
            self.proc("cluster0-shard-01-00.abcde.mongodb.net", "atlas-x-shard-1", "SHARD_PRIMARY"),
            self.proc("cluster0-shard-00-00.abcde.mongodb.net", None, "SHARD_MONGOS", port=27016),
            self.proc("cluster01-shard-00-00.abcde.mongodb.net", "atlas-y-shard-0", "REPLICA_PRIMARY"),
        ]
        hot = healthy_node(CACHE_FILL_RATIO=week(90), DIRTY_FILL_RATIO=week(10))
        metrics = {procs[0]["id"]: hot, procs[1]["id"]: healthy_node(), procs[2]["id"]: healthy_node()}
        results = rs.evaluate_cluster(FakeAtlas(self.CFG, metrics), "g", "Cluster0", rs.build_window(days=7), procs)
        by_name = {r["cluster"]: r for r in results}
        self.assertEqual(by_name["Cluster0 — replica set atlas-x-shard-0"]["verdict"], "scale_up")
        self.assertEqual(by_name["Cluster0 — replica set atlas-x-shard-1"]["verdict"], "scale_down_candidate")
        self.assertEqual(by_name["Cluster0 — mongos routers (1)"]["verdict"], "not_applicable")
        self.assertEqual(len(results), 3)  # Cluster01's process was not pulled in

    def test_no_matching_processes_is_insufficient_data_with_note(self):
        results = rs.evaluate_cluster(FakeAtlas(self.CFG, {}), "g", "Cluster0", rs.build_window(days=7), [])
        self.assertEqual(results[0]["verdict"], "insufficient_data")
        self.assertTrue(any("No processes matched" in n for n in results[0]["notes"]))

    def test_shared_tier_not_supported(self):
        cfg = dict(self.CFG, replicationSpecs=[{"regionConfigs": [{"electableSpecs": {"instanceSize": "M0"}}]}])
        results = rs.evaluate_cluster(FakeAtlas(cfg, {}), "g", "Cluster0", rs.build_window(days=7), [])
        self.assertEqual(results[0]["verdict"], "not_supported")


class MiscTests(unittest.TestCase):
    def test_timestamp_is_valid_utc(self):
        ts = rs.utc_now()
        self.assertTrue(ts.endswith("Z"))
        self.assertNotIn("+00:00", ts)

    def test_windows_are_whole_numbers(self):
        self.assertEqual(rs.build_window(days=7)["period"], "P7D")
        self.assertEqual(rs.build_window(hours=2)["period"], "PT2H")
        self.assertEqual(rs.build_window(hours=48)["granularity"], "PT1H")
        with self.assertRaises(ValueError):
            rs.build_window(days=0)

    def test_pctl(self):
        self.assertEqual(rs.pctl([1, 2, 3, 4, 5], 0.5), 3)
        self.assertIsNone(rs.pctl([], 0.5))

    def test_report_renders(self):
        r = dict(rs.evaluate_group([node(healthy_node())], ctx()), group_id="g", cluster="c",
                 cluster_name="c", current_tier="M10")
        md = rs.build_report([r], rs.build_window(days=7))
        self.assertIn("SCALE DOWN CANDIDATE", md)
        self.assertIn("### n0 (REPLICA_PRIMARY)", md)


if __name__ == "__main__":
    unittest.main()
