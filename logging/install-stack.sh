#!/usr/bin/env bash
set -euo pipefail

logging_dir="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
k=(kubectl --context kind-monitoring)

"${k[@]}" create namespace logging-lab --dry-run=client -o yaml |
  "${k[@]}" apply -f -

"${k[@]}" -n logging-lab create configmap loki-config \
  --from-file=config.yaml="$logging_dir/loki/config.yaml" \
  --dry-run=client -o yaml | "${k[@]}" apply -f -

"${k[@]}" -n logging-lab create configmap alloy-config \
  --from-file=config.alloy="$logging_dir/alloy/config.alloy" \
  --dry-run=client -o yaml | "${k[@]}" apply -f -

"${k[@]}" apply -f "$logging_dir/loki/deployment.yaml"
"${k[@]}" apply -f "$logging_dir/alloy/deployment.yaml"

"${k[@]}" -n logging-lab rollout status deployment/loki --timeout=300s
"${k[@]}" -n logging-lab rollout status deployment/alloy --timeout=300s
"${k[@]}" -n logging-lab get pods,pvc,svc

cat <<'NEXT'

In the existing Grafana, add a Loki data source with this URL:
  http://loki.logging-lab.svc.cluster.local:3100

Save & test, then open Explore and select Loki.
Generate fresh HTTP requests against logging-demo and query:
  {namespace="logging-lab",app="logging-demo"} | json
NEXT
