import unittest

import helpers  # noqa: F401  (puts scripts/ on sys.path)
import db_diagnostics as dd


def status(**overrides):
    s = {
        "host": "cluster0-shard-00-00.abcde.mongodb.net:27017",
        "opcounters": {"query": 100, "getmore": 10, "command": 1000},
        "metrics": {"queryExecutor": {"scanned": 500, "scannedObjects": 1000, "collectionScans": {"total": 5}},
                    "document": {"returned": 100}},
        "wiredTiger": {"cache": {"bytes currently in the cache": 400, "maximum bytes configured": 500,
                                 "modified pages evicted": 0, "unmodified pages evicted": 0,
                                 "pages read into cache": 10}},
        "connections": {"current": 60, "available": 1440},
    }
    s.update(overrides)
    return s


class SummarizeTests(unittest.TestCase):
    def test_rates_and_ratios(self):
        after = status(
            opcounters={"query": 160, "getmore": 10, "command": 1600},
            metrics={"queryExecutor": {"scanned": 500, "scannedObjects": 7000, "collectionScans": {"total": 65}},
                     "document": {"returned": 160}},
        )
        s = dd.summarize_server_status(status(), after, 60)
        self.assertEqual(s["opcounters_per_sec"]["query"], 1.0)
        self.assertEqual(s["docs_examined_per_sec"], 100.0)
        self.assertEqual(s["docs_returned_per_sec"], 1.0)
        self.assertEqual(s["examined_to_returned_ratio"], 100.0)
        self.assertEqual(s["collection_scans_per_sec"], 1.0)
        self.assertEqual(s["wt_cache_pct_used"], 80.0)
        self.assertEqual(s["connections_pct_used"], 4.0)

    def test_eviction_rate_sums_clean_and_dirty_pages(self):
        # MongoDB 8.0 has no single "pages evicted" counter (found on a live M10).
        after = status()
        after["wiredTiger"]["cache"].update({"modified pages evicted": 60, "unmodified pages evicted": 120})
        s = dd.summarize_server_status(status(), after, 60)
        self.assertEqual(s["wt_pages_evicted_per_sec"], 3.0)

    def test_missing_counters_are_none_not_zero(self):
        bare = {"opcounters": {}, "connections": {}}
        s = dd.summarize_server_status(bare, bare, 60)
        for key in ("wt_pages_evicted_per_sec", "docs_examined_per_sec", "connections_pct_used",
                    "wt_cache_pct_used", "collection_scans_per_sec"):
            self.assertIsNone(s[key], key)

    def test_mongos_explains_missing_cache_fields(self):
        mongos = status()
        del mongos["wiredTiger"]
        s = dd.summarize_server_status(mongos, mongos, 60)
        self.assertIsNone(s["wt_cache_pct_used"])
        self.assertTrue(any("mongos" in n for n in s["notes"]))

    def test_timestamp_is_valid_utc(self):
        self.assertNotIn("+00:00", dd.utc_now())


class SourceTests(unittest.TestCase):
    def test_source_records_hosts(self):
        class FakeClient:
            address = ("cluster0-shard-00-00.abcde.mongodb.net", 27017)

        hello = {"setName": "atlas-xyz-shard-0", "me": "cluster0-shard-00-00.abcde.mongodb.net:27017",
                 "hosts": ["cluster0-shard-00-00.abcde.mongodb.net:27017",
                           "cluster0-shard-00-01.abcde.mongodb.net:27017"]}
        src = dd.describe_source(FakeClient(), hello, status())
        self.assertFalse(src["is_mongos"])
        self.assertEqual(len(src["hosts"]), 2)


if __name__ == "__main__":
    unittest.main()
