// permissions_check.js
//
// Runs every MongoDB command db_diagnostics.py issues, reporting PASS/FAIL per
// command so you can verify the DB user's roles before running the Python
// script. Also confirms that find() is BLOCKED — the whole point of the custom
// role is that document data is never accessible.
//
// Usage:
//   mongosh "$MONGODB_URI" --quiet --file scripts/permissions_check.js
//
// Exit status:
//   0  all required commands succeeded (find may still be permitted; see WARN)
//   1  at least one required command failed — fix roles before running db_diagnostics.py

let passed = 0, failed = 0;

function check(label, fn) {
  try {
    fn();
    print(`PASS  ${label}`);
    passed++;
  } catch (e) {
    print(`FAIL  ${label}`);
    print(`      ${e.message}`);
    failed++;
  }
}

const admin = db.getSiblingDB("admin");

// -- Cluster / admin commands (db_diagnostics.py lines 195, 198, 202, 205, 207)
check("admin.ping             (any authenticated user)",
  () => admin.runCommand({ ping: 1 }));

check("admin.hello            (any user)",
  () => admin.runCommand({ hello: 1 }));

check("admin.serverStatus     (needs clusterMonitor)",
  () => admin.runCommand({ serverStatus: 1 }));

check("admin.listDatabases    (needs clusterMonitor)",
  () => admin.runCommand({ listDatabases: 1, nameOnly: true }));

// -- Per-database metadata commands (db_diagnostics.py lines 142, 148, 150)
let dbNames = [];
try {
  dbNames = admin.runCommand({ listDatabases: 1, nameOnly: true })
    .databases.map(d => d.name)
    .filter(n => !["admin", "local", "config"].includes(n));
} catch (e) {
  print("SKIP  per-database checks (listDatabases failed above)");
}

if (dbNames.length === 0) {
  print("SKIP  per-database checks (no user databases visible)");
}

for (const name of dbNames) {
  const target = db.getSiblingDB(name);

  check(`${name}.dbStats             (needs dbStats action)`,
    () => target.runCommand({ dbStats: 1 }));

  let collNames = [];
  check(`${name}.listCollections     (needs listCollections action)`,
    () => { collNames = target.getCollectionNames(); });

  if (collNames.length > 0) {
    check(`${name}.${collNames[0]}.collStats  (needs collStats action)`,
      () => target.runCommand({ collStats: collNames[0] }));
  }
}

// -- Confirm document reads are BLOCKED (script never calls find(); user
//    should not have that privilege). A blocked find is the desired outcome.
if (dbNames.length > 0) {
  const testDb = db.getSiblingDB(dbNames[0]);
  const colls = testDb.getCollectionNames();
  if (colls.length > 0) {
    const collName = colls[0];
    let findBlocked = false;
    try {
      testDb.getCollection(collName).find({}).limit(1).toArray();
    } catch (e) {
      findBlocked = true;
    }
    if (findBlocked) {
      print(`PASS  ${dbNames[0]}.${collName}.find is BLOCKED (user cannot read documents)`);
      passed++;
    } else {
      print(`WARN  ${dbNames[0]}.${collName}.find succeeded — user is over-privileged for db_diagnostics.py`);
      print(`      Consider replacing readAnyDatabase with a custom role granting only dbStats/collStats/listCollections.`);
    }
  }
}

print("");
print(`Summary: ${passed} passed, ${failed} failed`);
if (failed > 0) quit(1);
