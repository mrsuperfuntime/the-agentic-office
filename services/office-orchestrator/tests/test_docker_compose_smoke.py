import os
import subprocess
import time
from pathlib import Path

import pytest
import requests


REPO_ROOT = Path(__file__).resolve().parents[3]
BASE_COMPOSE = REPO_ROOT / "docker-compose.yml"
SMOKE_COMPOSE = Path(__file__).resolve().parent / "docker-compose.smoke.yml"


def _docker_compose_base_cmd(project_name: str) -> list[str] | None:
    docker_cmds = [
        ["docker", "compose"],
        ["docker-compose"],
    ]

    for cmd in docker_cmds:
        try:
            version_cmd = cmd + ["version"]
            proc = subprocess.run(version_cmd, capture_output=True, text=True, timeout=10)
            if proc.returncode == 0:
                if cmd == ["docker", "compose"]:
                    return ["docker", "compose", "-p", project_name]
                return ["docker-compose", "-p", project_name]
        except (FileNotFoundError, subprocess.TimeoutExpired):
            continue
    return None


def _wait_for_http(url: str, timeout_seconds: float = 180.0) -> None:
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        try:
            response = requests.get(url, timeout=2)
            if response.status_code == 200:
                return
        except requests.RequestException:
            pass
        time.sleep(2)
    raise TimeoutError(f"Timed out waiting for {url}")


@pytest.mark.integration
@pytest.mark.docker
def test_docker_compose_smoke_dispatch_and_persistence():
    if os.getenv("RUN_DOCKER_SMOKE") != "1":
        pytest.skip("Set RUN_DOCKER_SMOKE=1 to run docker integration smoke tests")

    project_name = "agentic_office_smoke"
    base_cmd = _docker_compose_base_cmd(project_name)
    if not base_cmd:
        pytest.skip("Docker Compose CLI not available")

    compose_cmd = base_cmd + ["-f", str(BASE_COMPOSE), "-f", str(SMOKE_COMPOSE)]

    up_cmd = compose_cmd + [
        "up",
        "-d",
        "--build",
        "postgres",
        "finance-office",
        "office-orchestrator",
    ]

    down_cmd = compose_cmd + ["down", "-v", "--remove-orphans"]

    try:
        up_proc = subprocess.run(up_cmd, cwd=str(REPO_ROOT), capture_output=True, text=True, timeout=600)
        assert up_proc.returncode == 0, up_proc.stdout + "\n" + up_proc.stderr

        base_url = "http://127.0.0.1:18000"
        headers = {"X-API-Key": "smoke-test-key"}

        _wait_for_http(f"{base_url}/health")

        message_response = requests.post(
            f"{base_url}/message",
            headers=headers,
            json={
                "from_office": "user",
                "to_office": "finance",
                "instruction": "Prepare a short budget snapshot for Q2.",
            },
            timeout=30,
        )
        assert message_response.status_code == 200, message_response.text

        stats_before = requests.get(f"{base_url}/stats", headers=headers, timeout=10)
        assert stats_before.status_code == 200, stats_before.text
        stats_before_json = stats_before.json()
        assert stats_before_json["total_transactions"] >= 1
        assert stats_before_json["message_transactions"] >= 1

        restart_proc = subprocess.run(
            compose_cmd + ["restart", "office-orchestrator"],
            cwd=str(REPO_ROOT),
            capture_output=True,
            text=True,
            timeout=180,
        )
        assert restart_proc.returncode == 0, restart_proc.stdout + "\n" + restart_proc.stderr

        _wait_for_http(f"{base_url}/health")

        stats_after = requests.get(f"{base_url}/stats", headers=headers, timeout=10)
        assert stats_after.status_code == 200, stats_after.text
        stats_after_json = stats_after.json()
        assert stats_after_json["total_transactions"] >= stats_before_json["total_transactions"]
    finally:
        subprocess.run(down_cmd, cwd=str(REPO_ROOT), capture_output=True, text=True, timeout=180)
