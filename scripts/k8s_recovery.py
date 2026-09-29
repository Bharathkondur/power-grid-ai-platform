"""Inject a liveness failure into this project's kind deployment and verify recovery."""

import json
import subprocess
import time


def kubectl(*args):
    return subprocess.check_output(
        ["kubectl", "--context", "kind-gridpulse", "-n", "gridpulse", *args], text=True
    )


def main():
    pod = json.loads(kubectl("get", "pods", "-l", "app=gridpulse-api", "-o", "json"))["items"][0]
    name = pod["metadata"]["name"]
    before = pod["status"]["containerStatuses"][0]["restartCount"]
    kubectl(
        "exec",
        name,
        "--",
        "python",
        "-c",
        "from pathlib import Path; Path('/tmp/gridpulse-unhealthy').touch()",
    )
    deadline = time.monotonic() + 120
    while time.monotonic() < deadline:
        pod = json.loads(kubectl("get", "pod", name, "-o", "json"))
        state = pod["status"]["containerStatuses"][0]
        if state["restartCount"] > before and state["ready"]:
            print(
                json.dumps(
                    {
                        "pod": name,
                        "restarts_before": before,
                        "restarts_after": state["restartCount"],
                        "ready": True,
                    }
                )
            )
            return
        time.sleep(3)
    raise RuntimeError("Pod did not recover within 120 seconds")


if __name__ == "__main__":
    main()
