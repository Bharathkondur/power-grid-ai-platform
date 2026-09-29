"""Capture compact, non-secret local verification evidence from real services and reports."""

import json
import subprocess
import xml.etree.ElementTree as ET
from datetime import UTC, datetime
from pathlib import Path

import httpx


def main():
    output = Path("docs/evidence")
    output.mkdir(parents=True, exist_ok=True)
    scan = json.loads(Path("runtime/image-scan.json").read_text())
    audit = json.loads(Path("runtime/dependency-audit.json").read_text())
    junit = ET.parse("runtime/junit.xml").getroot().find("testsuite")
    targets = httpx.get("http://localhost:9090/api/v1/targets").json()["data"]["activeTargets"]
    pods = json.loads(
        subprocess.check_output(
            [
                "kubectl",
                "--context",
                "kind-gridpulse",
                "-n",
                "gridpulse",
                "get",
                "pods",
                "-o",
                "json",
            ],
            text=True,
        )
    )["items"]
    result = {
        "captured_at": datetime.now(UTC).isoformat(),
        "scope": "local personal project",
        "tests": {
            name: junit.attrib[name] for name in ("tests", "failures", "errors", "skipped", "time")
        },
        "dependency_vulnerabilities": sum(len(p.get("vulns", [])) for p in audit["dependencies"]),
        "image_scan_policy": "Trivy HIGH/CRITICAL, ignore-unfixed, vulnerability scanner",
        "image_findings": sum(len(r.get("Vulnerabilities", [])) for r in scan["Results"]),
        "scanned_image": scan["ArtifactName"],
        "image_id": scan["Metadata"].get("ImageID"),
        "scrapes": [
            {"job": t["labels"]["job"], "health": t["health"], "last_error": t["lastError"]}
            for t in targets
        ],
        "compose_api": httpx.get("http://localhost:8000/ready").json(),
        "kubernetes_api": httpx.get("http://localhost:18000/ready").json(),
        "pods": [
            {
                "name": p["metadata"]["name"],
                "containers": [
                    {"name": c["name"], "ready": c["ready"], "restarts": c["restartCount"]}
                    for c in p["status"].get("containerStatuses", [])
                ],
            }
            for p in pods
        ],
        "rollback_demo": json.loads(Path("runtime/rollback-evidence.json").read_text()),
        "retraining_demo": json.loads(Path("runtime/retraining-evidence.json").read_text()),
        "hosted_ci": "see_github_actions_workflow",
        "s3": "not_provisioned",
        "entsoe": "not_run_no_token",
        "tls": "not_demonstrated_local_plaintext",
    }
    (output / "verification.json").write_text(json.dumps(result, indent=2))
    print("Saved docs/evidence/verification.json")


if __name__ == "__main__":
    main()
