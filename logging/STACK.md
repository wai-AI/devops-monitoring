# Loki and Alloy lab setup

These files add the logging backend and collector to the existing
`kind-monitoring` cluster. The previously deployed `logging-demo` application
must already exist in `logging-lab` with the Pod label `app=logging-demo`.

From the repository root:

```bash
bash logging/install-stack.sh
```

## Components

- Loki `3.7.0`, one monolithic instance, a 2 Gi PVC using StorageClass `standard`,
  TSDB schema v13 and filesystem storage. Log retention is configured to 24h;
  physical deletion is asynchronous. The Pod requests 256 Mi and is limited
  to 768 Mi. `GOMEMLIMIT=512MiB` is a Go runtime soft target, not a Kubernetes
  memory guarantee.
- Alloy `v1.13.0`, one Deployment, collecting application logs through the
  Kubernetes API. Discovery is restricted to namespace `logging-lab` and Pod
  label `app=logging-demo`. Its Role permits Pod discovery and log reads in
  that namespace. It requests 64 Mi and is limited to 256 Mi.
- Stream labels: `namespace`, `app`, `pod`, `container`. HTTP status remains in
  the JSON body and is parsed at query time.

Both image tags were checked for `linux/arm64` availability. Existing
Prometheus and Grafana releases are not upgraded by this setup.

Loki is unauthenticated and exposed only as a ClusterIP service inside this
local lab. It is not configured as a public endpoint. The PVC survives ordinary
Pod replacement but depends on the local kind node's lifetime. Alloy uses
ephemeral storage; this configuration does not guarantee exactly-once log
delivery across collector restarts.

## Grafana

Add a Loki data source using:

```text
http://loki.logging-lab.svc.cluster.local:3100
```

Leave authentication disabled for this local Loki service. Click Save & test,
then open Explore and select Loki. Generate fresh requests to the already
port-forwarded application:

```bash
curl -s -o /dev/null -w '%{http_code}\n' http://localhost:8081/
curl -s -o /dev/null -w '%{http_code}\n' http://localhost:8081/error
```

Query recent logs:

```logql
{namespace="logging-lab",app="logging-demo"} | json
```

Query server-error logs:

```logql
{namespace="logging-lab",app="logging-demo"} | json | status >= 500 | status < 600
```

Use a recent time range, such as Last 15 minutes. Initial requests generated
before installing Alloy may be outside that range, so always generate fresh
requests before checking ingestion.

## Troubleshooting

```bash
kubectl --context kind-monitoring -n logging-lab get pods,pvc
kubectl --context kind-monitoring -n logging-lab logs deployment/loki --tail=60
kubectl --context kind-monitoring -n logging-lab logs deployment/alloy --tail=60
kubectl --context kind-monitoring -n logging-lab describe pvc loki-data
```

Pod readiness alone does not verify end-to-end ingestion. Confirm that a fresh
HTTP request appears in Grafana with the expected JSON status.

ConfigMap changes do not automatically restart these Deployments. After editing
configuration and re-running the installer, restart the affected Deployment:

```bash
kubectl --context kind-monitoring -n logging-lab rollout restart deployment/alloy
```

Use `deployment/loki` instead if its configuration changed. Take one component
at a time and wait for its rollout to finish.

## Validation scope

YAML parsing, resource references, selectors, ports and shell syntax were
checked before delivery. No deployment was executed against your cluster.
Live component startup and the Grafana queries above are the integration tests.

Alert rules, Telegram contact points and the final dashboard are added in the
following steps; this bundle only sets up log collection and storage.

## Sources

- https://grafana.com/docs/loki/latest/configure/examples/configuration-examples/
- https://grafana.com/docs/alloy/latest/collect/logs-in-kubernetes/
- https://grafana.com/docs/alloy/latest/reference/components/loki/loki.source.kubernetes/
