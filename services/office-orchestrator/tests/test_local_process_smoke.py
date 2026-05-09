import os
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import requests


ORCHESTRATOR_DIR = Path(__file__).resolve().parents[1]
REPO_ROOT = ORCHESTRATOR_DIR.parents[1]
FINANCE_DIR = REPO_ROOT / "services" / "finance-office"


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def _wait_for_health(url: str, timeout_seconds: float = 30.0) -> None:
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        try:
            response = requests.get(url, timeout=1.0)
            if response.status_code == 200:
                return
        except requests.RequestException:
            pass
        time.sleep(0.25)
    raise TimeoutError(f"Timed out waiting for health endpoint: {url}")


def _stop_process(proc: subprocess.Popen | None) -> None:
    if not proc or proc.poll() is not None:
        return
    proc.terminate()
    try:
        proc.wait(timeout=8)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait(timeout=5)


def _start_finance_service(port: int) -> subprocess.Popen:
    env = os.environ.copy()
    env["PYTHONPATH"] = str(REPO_ROOT)
    # Avoid external network dependency during smoke tests.
    env["LLM_PRIMARY_PROVIDER"] = "disabled"
    env["LLM_FALLBACK_PROVIDER"] = "disabled"
    env["LLM_ENABLE_FALLBACK"] = "false"

    return subprocess.Popen(
        [
            sys.executable,
            "-m",
            "uvicorn",
            "main:app",
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
        ],
        cwd=str(FINANCE_DIR),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )


def _start_orchestrator(port: int, db_path: Path, office_url_overrides: dict | None = None) -> subprocess.Popen:
    env = os.environ.copy()
    env["ORCHESTRATOR_API_KEY"] = "local-smoke-key"
    env["DATABASE_URL"] = f"sqlite:///{db_path.as_posix()}"
    env["ORCHESTRATOR_MESSAGE_RATE_LIMIT"] = "50"
    env["ORCHESTRATOR_DISPATCH_RATE_LIMIT"] = "100"
    env["ORCHESTRATOR_REQUEST_RATE_LIMIT"] = "100"
    env["ORCHESTRATOR_RATE_WINDOW_SECONDS"] = "60"
    if office_url_overrides:
        for office_name, office_url in office_url_overrides.items():
            env_key = f"OFFICE_URL_{office_name.upper().replace('-', '_')}"
            env[env_key] = office_url

    return subprocess.Popen(
        [
            sys.executable,
            "-m",
            "uvicorn",
            "main:app",
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
        ],
        cwd=str(ORCHESTRATOR_DIR),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )


def test_local_process_smoke_dispatch_and_persistence():
    work_dir = Path(tempfile.mkdtemp(prefix="agentic_local_smoke_"))
    db_path = work_dir / "orchestrator_smoke.db"

    finance_port = _free_port()
    orchestrator_port = _free_port()

    finance_proc = None
    orchestrator_proc = None

    try:
        finance_proc = _start_finance_service(finance_port)
        _wait_for_health(f"http://127.0.0.1:{finance_port}/health")

        orchestrator_proc = _start_orchestrator(
            orchestrator_port,
            db_path,
            office_url_overrides={"finance": f"http://127.0.0.1:{finance_port}"},
        )
        base_url = f"http://127.0.0.1:{orchestrator_port}"
        headers = {"X-API-Key": "local-smoke-key"}
        _wait_for_health(f"{base_url}/health")

        dispatch = requests.post(
            f"{base_url}/message",
            headers=headers,
            json={
                "from_office": "user",
                "to_office": "finance",
                "instruction": "Prepare a short budget snapshot for Q2.",
            },
            timeout=20,
        )
        assert dispatch.status_code == 200, dispatch.text

        stats_before = requests.get(f"{base_url}/stats", headers=headers, timeout=10)
        assert stats_before.status_code == 200, stats_before.text
        stats_before_json = stats_before.json()
        assert stats_before_json["total_transactions"] >= 1
        assert stats_before_json["message_transactions"] >= 1

        _stop_process(orchestrator_proc)
        orchestrator_proc = _start_orchestrator(
            orchestrator_port,
            db_path,
            office_url_overrides={"finance": f"http://127.0.0.1:{finance_port}"},
        )
        _wait_for_health(f"{base_url}/health")

        stats_after = requests.get(f"{base_url}/stats", headers=headers, timeout=10)
        assert stats_after.status_code == 200, stats_after.text
        stats_after_json = stats_after.json()
        assert stats_after_json["total_transactions"] >= stats_before_json["total_transactions"]
    finally:
        _stop_process(orchestrator_proc)
        _stop_process(finance_proc)


def test_local_process_smoke_fallback_escalation():
    work_dir = Path(tempfile.mkdtemp(prefix="agentic_local_fallback_"))
    db_path = work_dir / "orchestrator_fallback.db"

    finance_port = _free_port()
    sales_dead_port = _free_port()
    orchestrator_port = _free_port()

    finance_proc = None
    orchestrator_proc = None

    try:
        finance_proc = _start_finance_service(finance_port)
        _wait_for_health(f"http://127.0.0.1:{finance_port}/health")

        orchestrator_proc = _start_orchestrator(
            orchestrator_port,
            db_path,
            office_url_overrides={
                "finance": f"http://127.0.0.1:{finance_port}",
                "sales": f"http://127.0.0.1:{sales_dead_port}",
            },
        )
        base_url = f"http://127.0.0.1:{orchestrator_port}"
        headers = {"X-API-Key": "local-smoke-key"}
        _wait_for_health(f"{base_url}/health")

        dispatch = requests.post(
            f"{base_url}/message",
            headers=headers,
            json={
                "from_office": "user",
                "to_office": "sales",
                "instruction": "Run a revenue health check with fallback.",
            },
            timeout=20,
        )
        assert dispatch.status_code == 200, dispatch.text
        dispatch_json = dispatch.json()
        assert dispatch_json["escalated"] is True
        assert dispatch_json["to_office"] == "finance"
        assert len(dispatch_json["attempts"]) == 2
        assert dispatch_json["attempts"][0]["office"] == "sales"
        assert dispatch_json["attempts"][1]["office"] == "finance"

        stats = requests.get(f"{base_url}/stats", headers=headers, timeout=10)
        assert stats.status_code == 200, stats.text
        stats_json = stats.json()
        assert stats_json["escalated_count"] >= 1

        dispatch_log = requests.get(
            f"{base_url}/dispatch-log?limit=5&office=finance&status=completed",
            headers=headers,
            timeout=10,
        )
        assert dispatch_log.status_code == 200, dispatch_log.text
        logs = dispatch_log.json()["logs"]
        assert len(logs) >= 1
        latest = logs[-1]
        assert latest["escalated"] is True
        assert len(latest["attempts"]) == 2
    finally:
        _stop_process(orchestrator_proc)
        _stop_process(finance_proc)
