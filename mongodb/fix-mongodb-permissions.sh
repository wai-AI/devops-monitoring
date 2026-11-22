#!/usr/bin/env bash
# Add the exact missing privilege observed in the live MongoDB log.
# Existing credentials, stored data and the monitor user's other roles remain.
set -euo pipefail

kubectl --context kind-monitoring -n monitoring-lab exec -i deployment/mongodb -- \
  mongosh --quiet --norc --file /dev/stdin <<'MONGODB_JS'
const admin = db.getSiblingDB("admin");
admin.auth("root", process.env.MONGO_INITDB_ROOT_PASSWORD);

const roleName = "exporterReadSystemVersion";
const privileges = [{
  resource: { db: "admin", collection: "system.version" },
  actions: ["find"]
}];
if (admin.getRole(roleName)) {
  admin.grantPrivilegesToRole(roleName, privileges);
} else {
  admin.createRole({ role: roleName, privileges: privileges, roles: [] });
}
admin.grantRolesToUser("monitor", [{ role: roleName, db: "admin" }]);

// Verify on a new connection authenticated only as the monitor user.
const probeConnection = new Mongo("mongodb://127.0.0.1:27017/admin");
const monitorAdmin = probeConnection.getDB("admin");
monitorAdmin.auth("monitor", process.env.MONGODB_MONITOR_PASSWORD);
monitorAdmin.getCollection("system.version").find({ _id: "shardIdentity" }).limit(1).toArray();
print("Verified: monitor can read admin.system.version");
MONGODB_JS
