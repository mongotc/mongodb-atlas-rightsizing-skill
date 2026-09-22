import unittest

import helpers  # noqa: F401  (puts scripts/ on sys.path)
import merge_verdict as mv

HOST = "cluster0-shard-00-00.abcde.mongodb.net"


def row(triggers=(), verdict="scale_up", confidence="high", hosts=(HOST,), cluster="Cluster0"):
    return {"group_id": "g", "cluster_name": cluster, "cluster": cluster, "current_tier": "M10",
            "verdict": verdict, "confidence": confidence, "triggers": list(triggers),
            "reasons": ["r"], "borderline": [], "notes": [],
            "nodes": [{"node": "n0", "hosts": list(hosts), "metric_summary": {}}]}


def diagnostics(hosts=(HOST + ":27017",), is_mongos=False, **summary):
    base = {"wt_cache_pct_used": 79.5, "wt_cache_bytes_max": 536870912, "connections_pct_used": 4.0,
            "wt_pages_read_into_cache_per_sec": 3.35, "wt_pages_evicted_per_sec": 0.0}
    base.update(summary)
    return {"sampled_at": "2026-09-22T16:25:11Z", "source": {"hosts": list(hosts), "is_mongos": is_mongos},
            "server_status_summary": base,
            # The real M10 from references/db-diagnostics.md: ~18x the 512 MB cache.
            "data_footprint": {"POCDB": {"data_size_bytes": 9005093523, "index_size_bytes": 725471232}}}


def report(*rows):
    return {"groupIds": ["g"], "windowLabel": "7 days", "results": list(rows)}


class MergeTests(unittest.TestCase):
    def merged_row(self, r, db):
        merged, _ = mv.merge(report(r), db)
        return merged[0]

    def test_data_larger_than_cache_without_page_faults_is_not_high_confidence(self):
        m = self.merged_row(row(["cache_fill"]), diagnostics())
        self.assertEqual([f["signal"] for f in m["combined_analysis"]], ["memory_inconclusive"])
        self.assertEqual(m["combined_analysis"][0]["relation"], "context")
        self.assertNotIn("HIGH", m["combined_analysis"][0]["note"])

    def test_data_larger_than_cache_with_page_faults_agrees(self):
        m = self.merged_row(row(["cache_fill", "page_faults"]), diagnostics())
        self.assertEqual(m["combined_analysis"][0]["signal"], "memory_consistent")

    def test_memory_unconfirmed_is_labeled_disagreement_and_lowers_confidence(self):
        db = diagnostics(wt_cache_pct_used=30)
        db["data_footprint"] = {"small": {"data_size_bytes": 1000, "index_size_bytes": 10}}
        merged, warnings = mv.merge(report(row(["memory"])), db)
        f = merged[0]["combined_analysis"][0]
        self.assertEqual(f["relation"], "disagrees")
        self.assertEqual(merged[0]["merged_confidence"], "low")
        md = mv.build_merged_report(report(), merged, warnings, db, "db.json")
        self.assertIn("[DISAGREES]", md)
        self.assertNotIn("[AGREES]", md)

    def test_inefficient_scans_with_collection_scans_lead_with_index_fix(self):
        db = diagnostics(docs_examined_per_sec=5000, docs_returned_per_sec=10, examined_to_returned_ratio=500.0,
                         collection_scans_per_sec=2.0)
        merged, warnings = mv.merge(report(row(["cpu"])), db)
        self.assertTrue(merged[0]["combined_analysis"][0].get("lead_with_schema_fix"))
        md = mv.build_merged_report(report(), merged, warnings, db, "db.json")
        self.assertIn("Recommended first step: index/query review", md)

    def test_aggregation_heavy_without_collection_scans_is_not_blamed_on_indexes(self):
        db = diagnostics(docs_examined_per_sec=5000, docs_returned_per_sec=0, examined_to_returned_ratio="inf",
                         collection_scans_per_sec=0.0)
        m = self.merged_row(row(["cpu"]), db)
        self.assertEqual(m["combined_analysis"][0]["relation"], "context")

    def test_disk_signal_needs_real_cache_churn(self):
        quiet = self.merged_row(row(["disk_latency_read"]), diagnostics(wt_cache_pct_used=30))
        self.assertEqual(quiet["combined_analysis"], [])
        churn = self.merged_row(row(["disk_latency_read"]),
                                diagnostics(wt_cache_pct_used=95, wt_pages_evicted_per_sec=50))
        self.assertEqual(churn["combined_analysis"][0]["signal"], "disk_cache_miss_driven")

    def test_connections_message_uses_report_window(self):
        m = self.merged_row(row(["connections"]), diagnostics())
        self.assertIn("over 7 days", m["combined_analysis"][0]["note"])
        self.assertEqual(m["merged_confidence"], "medium")

    def test_not_evaluated_rows_are_skipped(self):
        rows = [row([], verdict="insufficient_data"), row(["connections"], verdict="not_applicable")]
        merged, _ = mv.merge(report(*rows), diagnostics(connections_pct_used=90))
        self.assertTrue(all(not m["applies"] and not m["combined_analysis"] for m in merged))

    def test_diagnostics_from_another_cluster_is_rejected(self):
        with self.assertRaises(SystemExit):
            mv.merge(report(row(["cpu"])), diagnostics(hosts=("other-shard-00-00.zzz.mongodb.net:27017",)))
        merged, warnings = mv.merge(report(row(["cpu"])),
                                    diagnostics(hosts=("other-shard-00-00.zzz.mongodb.net:27017",)),
                                    allow_host_mismatch=True)
        self.assertTrue(warnings)

    def test_snapshot_only_applies_to_its_own_replica_set(self):
        shard0 = row(["cpu"], cluster="Cluster0")
        shard1 = row(["cpu"], cluster="Cluster0", hosts=("cluster0-shard-01-00.abcde.mongodb.net",))
        merged, _ = mv.merge(report(shard0, shard1), diagnostics())
        self.assertEqual([m["applies"] for m in merged], [True, False])

    def test_mongos_snapshot_applies_to_all_shards_with_warning(self):
        shard0 = row(["cpu"])
        shard1 = row(["cpu"], hosts=("cluster0-shard-01-00.abcde.mongodb.net",))
        merged, warnings = mv.merge(report(shard0, shard1), diagnostics(is_mongos=True))
        self.assertEqual([m["applies"] for m in merged], [True, True])
        self.assertTrue(any("hot shard" in w for w in warnings))

    def test_atlas_only_mode(self):
        merged, warnings = mv.merge(report(row(["cpu"])), None)
        md = mv.build_merged_report(report(), merged, warnings, None, None)
        self.assertIn("ATLAS-ONLY", md)

    def test_unreadable_diagnostics_path_is_an_error(self):
        with self.assertRaises(SystemExit):
            mv.main(["--rightsizing-report", __file__, "--db-diagnostics", "does-not-exist.json"])


if __name__ == "__main__":
    unittest.main()
