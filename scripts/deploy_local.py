"""Deploy the chart into a dedicated kind cluster; keep secrets out of command output."""

import argparse
import json
import os
import shutil
import subprocess
from pathlib import Path

from dotenv import dotenv_values


def command(args: list[str], **kwargs):
    return subprocess.run(args, check=True, text=True, **kwargs)


def main():
    args = argparse.ArgumentParser()
    args.add_argument(
        "--ci", action="store_true", help="Use Compose container IPs on a Linux runner"
    )
    options = args.parse_args()
    kind = shutil.which("kind") or str(Path(".tools/kind.exe").resolve())
    helm = shutil.which("helm") or str(Path(".tools/windows-amd64/helm.exe").resolve())
    clusters = command([kind, "get", "clusters"], capture_output=True).stdout.splitlines()
    if "gridpulse" not in clusters:
        command(
            [
                kind,
                "create",
                "cluster",
                "--name",
                "gridpulse",
                "--image",
                "kindest/node:v1.33.1",
                "--config",
                "deploy/k8s/kind.yaml",
                "--wait",
                "180s",
            ]
        )
    command([kind, "load", "docker-image", "gridpulse-ai:0.1.0", "--name", "gridpulse"])
    kube = ["kubectl", "--context", "kind-gridpulse"]
    command(
        kube + ["apply", "-f", "-"],
        input=json.dumps(
            {
                "apiVersion": "v1",
                "kind": "Namespace",
                "metadata": {"name": "gridpulse"},
            }
        ),
    )
    config = {**dotenv_values(".env"), **os.environ}
    db_host, mlflow_host, mqtt_host = ("host.docker.internal",) * 3
    if options.ci:
        subprocess.run(
            ["docker", "network", "connect", "gridpulse_default", "gridpulse-control-plane"],
            check=False,
        )

        def container_ip(service):
            details = json.loads(
                command(["docker", "inspect", f"gridpulse-{service}-1"], capture_output=True).stdout
            )
            return details[0]["NetworkSettings"]["Networks"]["gridpulse_default"]["IPAddress"]

        db_host, mlflow_host, mqtt_host = [
            container_ip(name) for name in ("postgres", "mlflow", "mqtt")
        ]
    secret = {
        "apiVersion": "v1",
        "kind": "Secret",
        "metadata": {
            "name": "gridpulse-secrets",
            "namespace": "gridpulse",
        },
        "type": "Opaque",
        "stringData": {
            "GRIDPULSE_DATABASE_URL": f"postgresql+psycopg://gridpulse:{config['POSTGRES_PASSWORD']}@{db_host}:5432/gridpulse",
        },
    }
    command(kube + ["apply", "-f", "-"], input=json.dumps(secret))
    command(
        [
            helm,
            "upgrade",
            "--install",
            "gridpulse",
            "deploy/helm/gridpulse",
            "--kube-context",
            "kind-gridpulse",
            "--namespace",
            "gridpulse",
            "-f",
            "deploy/helm/gridpulse/values-dev.yaml",
            "--set",
            f"config.GRIDPULSE_MLFLOW_URI=http://{mlflow_host}:5000",
            "--set",
            f"config.GRIDPULSE_MQTT_HOST={mqtt_host}",
            "--wait",
            "--timeout",
            "5m",
        ]
    )
    command(kube + ["get", "pods", "-n", "gridpulse"])


if __name__ == "__main__":
    main()
