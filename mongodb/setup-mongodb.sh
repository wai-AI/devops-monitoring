#!/usr/bin/env bash
# Run from the extracted folder: bash setup-mongodb.sh
set -euo pipefail

bundle_dir="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
lab_kubectl=(kubectl --context kind-monitoring)

command -v kubectl >/dev/null
command -v openssl >/dev/null
"${lab_kubectl[@]}" get nodes

# Reuse the existing lab namespace and credentials on repeated runs.
"${lab_kubectl[@]}" create namespace monitoring-lab --dry-run=client -o yaml |
  "${lab_kubectl[@]}" apply -f -

existing_secret="$("${lab_kubectl[@]}" -n monitoring-lab get secret mongodb-credentials --ignore-not-found -o name)"
if [[ -z "$existing_secret" ]]; then
  umask 077
  credential_dir="$(mktemp -d)"
  trap 'rm -rf -- "$credential_dir"' EXIT
  openssl rand -hex 24 | tr -d '\n' > "$credential_dir/root-password"
  openssl rand -hex 24 | tr -d '\n' > "$credential_dir/monitor-password"
  "${lab_kubectl[@]}" -n monitoring-lab create secret generic mongodb-credentials \
    --from-file=root-password="$credential_dir/root-password" \
    --from-file=monitor-password="$credential_dir/monitor-password"
fi

"${lab_kubectl[@]}" apply -f "$bundle_dir/mongodb.yaml"
"${lab_kubectl[@]}" -n monitoring-lab rollout status deployment/mongodb --timeout=300s
bash "$bundle_dir/fix-mongodb-permissions.sh"
"${lab_kubectl[@]}" -n monitoring-lab rollout status deployment/mongodb-exporter --timeout=180s
"${lab_kubectl[@]}" -n monitoring-lab get pods,pvc,svc

cat <<'NEXT'

Next, in Grafana Explore, run these queries separately:
  up{job="mongodb-exporter"}
  mongodb_up{job="mongodb-exporter"}
Expected after a successful scrape and database initialization: 1 for both.

Find the actual assertion metric names:
  {job="mongodb-exporter",__name__=~"mongodb_.*assert.*"}

If deployment startup fails:
  kubectl --context kind-monitoring -n monitoring-lab get pods,pvc
  kubectl --context kind-monitoring -n monitoring-lab logs deployment/mongodb --tail=60
  kubectl --context kind-monitoring -n monitoring-lab logs deployment/mongodb-exporter --tail=60
NEXT
