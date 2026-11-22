#!/usr/bin/env python3
"""Expose metrics inside the existing local kind cluster; Python stdlib only.

Run on the Mac: python3 fix-kind-metrics.py
Scope: Docker node monitoring-control-plane, kubectl context kind-monitoring.
No Helm release, ServiceMonitor, database or persistent volume is removed.
Backups and rollback instructions are saved before any configuration mutation.
"""
import datetime
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time

NODE = "monitoring-control-plane"
KUBE = ["kubectl", "--context", "kind-monitoring"]
MANIFESTS = "/etc/kubernetes/manifests"


def run(args, data=None, check=True):
    result = subprocess.run(args, input=data, text=True, capture_output=True)
    if check and result.returncode:
        raise RuntimeError("Command failed: " + " ".join(args[:8]) + "\n" + result.stderr.strip())
    return result


def output(args):
    return run(args).stdout


def docker_write(path, content):
    run(["docker", "exec", "-i", NODE, "sh", "-c", 'umask 077; cat > "$1"', "sh", path], content)


def replace_flag(text, flag, expected, replacement):
    pattern = re.compile(r"(?m)^([ \t]*-[ \t]+" + re.escape(flag) + r"=)([^\r\n]+)$")
    matches = list(pattern.finditer(text))
    if len(matches) != 1:
        raise RuntimeError("Expected exactly one " + flag + " flag; no changes applied.")
    current = matches[0].group(2).strip()
    print("  " + flag + "=" + current, flush=True)
    if current not in (expected, replacement):
        raise RuntimeError("Unexpected " + flag + " value; no changes applied: " + current)
    return pattern.sub(lambda m: m.group(1) + replacement, text)


def main():
    # Check the actual Docker labels, context and node before selecting any file.
    labels = json.loads(output(["docker", "inspect", NODE, "--format", "{{json .Config.Labels}} "]))
    if labels.get("io.x-k8s.kind.cluster") != "monitoring":
        raise RuntimeError("Docker container is not a node of the monitoring kind cluster.")
    info = json.loads(output(KUBE + ["get", "node", NODE, "-o", "json"]))
    if not info.get("spec", {}).get("providerID", "").startswith("kind://"):
        raise RuntimeError("Selected Kubernetes node is not a kind node.")
    ip = next(a["address"] for a in info["status"]["addresses"] if a["type"] == "InternalIP")
    run(["docker", "exec", NODE, "sh", "-c", "command -v bash >/dev/null && command -v timeout >/dev/null"])

    print("Checking current metrics bindings on " + NODE + " (" + ip + ")", flush=True)
    files = {}
    for name in ("kube-controller-manager.yaml", "kube-scheduler.yaml", "etcd.yaml"):
        original = output(["docker", "exec", NODE, "cat", MANIFESTS + "/" + name])
        if name == "etcd.yaml":
            updated = replace_flag(original, "--listen-metrics-urls", "http://127.0.0.1:2381", "http://0.0.0.0:2381")
        else:
            updated = replace_flag(original, "--bind-address", "127.0.0.1", "0.0.0.0")
        files[name] = (original, updated)

    cm = json.loads(output(KUBE + ["-n", "kube-system", "get", "configmap", "kube-proxy", "-o", "json"]))
    config = cm.get("data", {}).get("config.conf")
    if not isinstance(config, str):
        raise RuntimeError("kube-proxy config.conf is missing; no changes applied.")
    pattern = re.compile(r"(?m)^([ \t]*metricsBindAddress:)[^\r\n]*$")
    matches = list(pattern.finditer(config))
    if len(matches) != 1:
        raise RuntimeError("Expected one metricsBindAddress field; no changes applied.")
    current = matches[0].group(0).split(":", 1)[1].strip().strip('\"\'')
    print("  kube-proxy metricsBindAddress=" + repr(current), flush=True)
    if current not in ("", "127.0.0.1:10249", "0.0.0.0:10249"):
        raise RuntimeError("Unexpected kube-proxy metrics address; no changes applied.")
    updated_config = pattern.sub(lambda m: m.group(1) + " 0.0.0.0:10249", config)

    changed_files = [name for name, (old, new) in files.items() if old != new]
    proxy_changed = config != updated_config
    if not changed_files and not proxy_changed:
        print("All bindings are already configured. No configuration changes needed.")
    else:
        stamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        backup = Path.cwd() / ("kind-metrics-backup-" + stamp)
        backup.mkdir(mode=0o700)
        node_backup = "/root/monitoring-metrics-backup-" + stamp
        run(["docker", "exec", NODE, "mkdir", "-p", node_backup])
        for name, (original, updated) in files.items():
            (backup / name).write_text(original)
            docker_write(node_backup + "/" + name, original)
            if name in changed_files:
                docker_write(node_backup + "/new-" + name, updated)
        (backup / "kube-proxy-original.json").write_text(json.dumps(cm, indent=2))
        patch_path = backup / "kube-proxy-restore-patch.json"
        patch_path.write_text(json.dumps({"data": {"config.conf": config}}))
        rollback = [
            "#!/usr/bin/env bash", "set -euo pipefail",
            'rollback_dir="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"',
            'kubectl --context kind-monitoring -n kube-system patch configmap kube-proxy --type merge --patch-file "$rollback_dir/kube-proxy-restore-patch.json"',
            "kubectl --context kind-monitoring -n kube-system rollout restart daemonset/kube-proxy",
        ]
        for name in changed_files:
            rollback.append("docker exec " + NODE + " sh -c 'cp " + node_backup + "/" + name + " " + node_backup + "/restore-" + name + " && mv " + node_backup + "/restore-" + name + " " + MANIFESTS + "/" + name + "'")
        (backup / "rollback.sh").write_text("\n".join(rollback) + "\n")
        print("Backups: " + str(backup), flush=True)
        print("Rollback, if needed: bash " + str(backup / "rollback.sh"), flush=True)

        # Patch only this field, preserving kubeconfig.conf and all other data.
        if proxy_changed:
            patch = json.dumps({"data": {"config.conf": updated_config}})
            print(output(KUBE + ["-n", "kube-system", "patch", "configmap", "kube-proxy", "--type", "merge", "-p", patch]).strip(), flush=True)
            print(output(KUBE + ["-n", "kube-system", "rollout", "restart", "daemonset/kube-proxy"]).strip(), flush=True)

        # Rename fully prepared files into the watched directory. Backups and
        # temporary files stay outside /etc/kubernetes/manifests.
        for name in changed_files:
            print("Updating " + name + "; its static Pod will restart.", flush=True)
            run(["docker", "exec", NODE, "mv", node_backup + "/new-" + name, MANIFESTS + "/" + name])

    # Connectivity is tested inside the kind node's network, not from macOS.
    # Every probe command has a bounded timeout; progress remains visible.
    probe = ('for port in 10249 10257 10259 2381; do '
             'timeout 2 bash -c "exec 3<>/dev/tcp/$1/$port" >/dev/null 2>&1 || exit 1; '
             'done')
    for attempt in range(40):
        ready = run(["docker", "exec", NODE, "bash", "-c", probe, "bash", ip], check=False)
        if ready.returncode == 0:
            print("TCP reachable on node IP: 10249, 10257, 10259, 2381", flush=True)
            break
        print("Waiting for component restarts (attempt " + str(attempt + 1) + "/40)...", flush=True)
        time.sleep(3)
    else:
        raise RuntimeError("Not all metrics ports became reachable. Use the printed backup/rollback path and inspect component logs.")

    print("Refresh Prometheus Targets after another scrape.")
    print("Run: up == 0")
    print("TCP reachability alone does not verify HTTP/TLS/authentication or successful scraping.")
    print("If a target remains DOWN, inspect its new Last Error.")


if __name__ == "__main__":
    try:
        main()
    except (RuntimeError, OSError, ValueError, KeyError, StopIteration) as exc:
        print("ERROR: " + str(exc), file=sys.stderr)
        sys.exit(1)
