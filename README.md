# Kubernetes Monitoring with Prometheus and Grafana

A local Kubernetes monitoring setup covering node resources, container health, Kubernetes events, and MongoDB. This repository contains the configuration, dashboard export, test manifests, and results.

## Environment

- MacBook Air M1 with 8 GB RAM.
- OrbStack as the Docker runtime.
- A single-node kind cluster named `monitoring`.
- Kubernetes v1.35.0, ARM64.
- Approximately 4 GiB of memory available to the Kubernetes node.

## Monitoring setup

The main stack was installed using the `kube-prometheus-stack` Helm chart.

Prometheus collects metrics from node-exporter, kubelet, kube-state-metrics, the events exporter, and the MongoDB exporter. Grafana uses Prometheus as its data source. Alerting rules are evaluated by Prometheus.

Kubernetes monitoring components run in the `monitoring` namespace. MongoDB and test workloads use `monitoring-lab`.

## Deployment

The following commands describe deployment to a fresh local cluster. Docker, kind, kubectl, Helm, and Python 3 must be installed.

```bash
kind create cluster --name monitoring --image kindest/node:v1.35.0

helm repo add prometheus-community https://prometheus-community.github.io/helm-charts
helm repo update

helm install monitoring prometheus-community/kube-prometheus-stack \
  --namespace monitoring \
  --create-namespace \
  --kube-context kind-monitoring
```

Deploy MongoDB, the events exporter, and the alerting rules:

```bash
bash mongodb/setup-mongodb.sh

kubectl --context kind-monitoring apply -f events/events-exporter.yaml

kubectl --context kind-monitoring apply -f alerts/monitoring-alerts.yaml
```

Configure the local kind node to expose control-plane metrics:

```bash
python3 scripts/fix-kind-metrics.py
```

The script checks the existing configuration, creates backups, and updates the metrics bindings. The affected Kubernetes components restart during this change.

## Access

Run each port-forward command in a separate terminal.

Grafana:

```bash
kubectl --context kind-monitoring -n monitoring \
  port-forward svc/monitoring-grafana 3030:80
```

Open [Grafana](http://localhost:3030). The username is `admin`. Retrieve the password locally:

```bash
kubectl --context kind-monitoring -n monitoring \
  get secret monitoring-grafana \
  -o jsonpath='{.data.admin-password}' | base64 -d
```

Prometheus:

```bash
kubectl --context kind-monitoring -n monitoring \
  port-forward svc/monitoring-kube-prometheus-prometheus 9090:9090
```

Open [Prometheus](http://localhost:9090).

The [dashboard export](<dashboards/Kubernetes Infrastructure-1795370990690.json>) uses the Grafana V2 schema. Import it into a Grafana instance that supports V2.

## Dashboard panels

| Panel | Metrics | Purpose |
|---|---|---|
| Node CPU usage | `node_cpu_seconds_total` | Shows CPU utilization and helps identify sustained load. |
| Node memory usage | `node_memory_MemTotal_bytes`, `node_memory_MemAvailable_bytes` | Shows the percentage of memory currently unavailable for new workloads. |
| Container restarts | `kube_pod_container_status_restarts_total` | Shows restart increases over the last 15 minutes to highlight unstable containers. |
| Container memory limits | `kube_pod_container_resource_limits{resource="memory"}` | Shows configured memory limits when investigating OOM failures. |
| Container CPU limits | `kube_pod_container_resource_limits{resource="cpu"}` | Shows configured CPU limits for each container. |
| Last termination: OOMKilled | `kube_pod_container_status_last_terminated_reason` | Identifies containers whose latest recorded termination reason was OOMKilled. |
| Kubernetes events | `kube_event_exporter` | Provides context for scheduling and workload lifecycle problems. |
| MongoDB availability | `mongodb_up` | Shows whether the exporter can connect to MongoDB. |
| MongoDB connections | `mongodb_ss_connections` | Shows current client connections. |
| MongoDB assertions | `mongodb_asserts_total` | Shows assertion increases over five minutes, grouped by type. |

Resource limits describe configuration, not actual resource consumption. The OOM panel shows the latest recorded termination reason, not a complete incident history.

## Alerting

The Kubernetes rules are based on [Awesome Prometheus Alerts](https://samber.github.io/awesome-prometheus-alerts/rules/orchestrators/kubernetes/).

They cover:

- Nodes becoming NotReady.
- Memory and disk pressure.
- Unhealthy Pods and CrashLoopBackOff.
- Deployment replica mismatches.
- Recent restarts with OOMKilled as the latest termination reason.

The OOM expression was adapted to use `increase()` for restart counters. Additional rules monitor MongoDB availability and provide a dedicated one-minute lab test.

Alertmanager is included in the stack. External notifications were not configured.

## Tests and results

### OOMKilled

The `oom-demo` container had a `64Mi` memory limit and attempted to allocate `128Mi`.

Kubernetes reported `OOMKilled`, exit code `137`, and a container restart. The Grafana panel displayed the affected container.

![OOMKilled test](<docs/screenshots/image(20261122-170520).png>)

### Kubernetes events

The `events-demo` Pod requested more CPU than the node could provide. It remained Pending, and the events panel displayed a `Warning` event with the reason `FailedScheduling`.

![Kubernetes events](<docs/screenshots/image(20261122-172339).png>)

### Alert firing

The `alert-demo` Pod was also intentionally unschedulable. The dedicated `MonitoringLabPodNotHealthy` rule reached the Firing state after its one-minute pending period.

The test Pod was then deleted.

![Alert firing](<docs/screenshots/image(20261122-174911).png>)

### Final scrape check

After fixing the metrics bindings, the following query returned an empty result:

```promql
up == 0
```

At the time of verification, no discovered targets had failed scrapes.

![Final scrape check](<docs/screenshots/image(20261122-180558).png>)


