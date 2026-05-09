import os
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import requests


SERVICE_DIR = Path(__file__).resolve().parents[1]


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def _wait_for_health(base_url: str, timeout_seconds: float = 20.0) -> None:
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        try:
            response = requests.get(f"{base_url}/health", timeout=1.0)
            if response.status_code == 200:
                return
        except requests.RequestException:
            pass
        time.sleep(0.2)
    raise TimeoutError("Timed out waiting for orchestrator /health endpoint")


class LiveServer:
    def __init__(self):
        self.port = _free_port()
        self.base_url = f"http://127.0.0.1:{self.port}"
        self.api_key = "live-test-key"
        self._tmp_dir = Path(tempfile.mkdtemp(prefix="orchestrator_live_"))
        self._proc = None

    def start(self):
        db_file = self._tmp_dir / "live_test.db"
        env = os.environ.copy()
        env["ORCHESTRATOR_API_KEY"] = self.api_key
        env["DATABASE_URL"] = f"sqlite:///{db_file.as_posix()}"
        env["ORCHESTRATOR_MESSAGE_RATE_LIMIT"] = "2"
        env["ORCHESTRATOR_DISPATCH_RATE_LIMIT"] = "3"
        env["ORCHESTRATOR_REQUEST_RATE_LIMIT"] = "3"
        env["ORCHESTRATOR_RATE_WINDOW_SECONDS"] = "60"

        self._proc = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "uvicorn",
                "main:app",
                "--host",
                "127.0.0.1",
                "--port",
                str(self.port),
            ],
            cwd=str(SERVICE_DIR),
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )

        try:
            _wait_for_health(self.base_url)
        except Exception as exc:
            output = ""
            if self._proc and self._proc.stdout:
                output = self._proc.stdout.read()
            self.stop()
            raise RuntimeError(f"Failed to start live server: {exc}\n{output}") from exc

    def stop(self):
        if self._proc and self._proc.poll() is None:
            self._proc.terminate()
            try:
                self._proc.wait(timeout=8)
            except subprocess.TimeoutExpired:
                self._proc.kill()
                self._proc.wait(timeout=5)


live_server = LiveServer()


def setup_module(_module):
    live_server.start()


def teardown_module(_module):
    live_server.stop()


def _auth_headers() -> dict:
    return {"X-API-Key": live_server.api_key}


def _metric_value(metrics_body: str, metric_name: str) -> int:
    for line in metrics_body.splitlines():
        if line.startswith(f"{metric_name} "):
            return int(float(line.split(" ", 1)[1]))
    raise AssertionError(f"Metric not found: {metric_name}")


def test_http_auth_required_for_sensitive_endpoints():
    health = requests.get(f"{live_server.base_url}/health", timeout=3)
    assert health.status_code == 200

    message = requests.post(
        f"{live_server.base_url}/message",
        json={"to_office": "finance", "instruction": "test auth"},
        timeout=5,
    )
    assert message.status_code == 401

    dispatch = requests.get(f"{live_server.base_url}/dispatch-log", timeout=5)
    assert dispatch.status_code == 401

    logs = requests.get(f"{live_server.base_url}/logs", timeout=5)
    assert logs.status_code == 401

    stats = requests.get(f"{live_server.base_url}/stats", timeout=5)
    assert stats.status_code == 401

    metrics = requests.get(f"{live_server.base_url}/metrics", timeout=5)
    assert metrics.status_code == 401


def test_http_rate_limit_enforced_on_message_endpoint():
    payload = {"to_office": "not-a-real-office", "instruction": "rate limit probe"}

    first = requests.post(
        f"{live_server.base_url}/message",
        json=payload,
        headers=_auth_headers(),
        timeout=5,
    )
    assert first.status_code == 400

    second = requests.post(
        f"{live_server.base_url}/message",
        json=payload,
        headers=_auth_headers(),
        timeout=5,
    )
    assert second.status_code == 400

    third = requests.post(
        f"{live_server.base_url}/message",
        json=payload,
        headers=_auth_headers(),
        timeout=5,
    )
    assert third.status_code == 429


def test_http_metrics_prometheus_format():
    response = requests.get(
        f"{live_server.base_url}/metrics",
        headers=_auth_headers(),
        timeout=5,
    )
    assert response.status_code == 200

    body = response.text
    assert "# HELP agentic_office_transactions_total" in body
    assert "# TYPE agentic_office_transactions_total counter" in body
    assert "agentic_office_transactions_total" in body
    assert "agentic_office_transactions_by_status{status=\"completed\"}" in body
    assert "agentic_office_rate_limit_config{endpoint=\"message\"}" in body
    assert "agentic_office_rate_bucket_events{endpoint=\"message\"}" in body


def test_http_metrics_change_after_dispatch_attempt():
    before = requests.get(
        f"{live_server.base_url}/metrics",
        headers=_auth_headers(),
        timeout=5,
    )
    assert before.status_code == 200
    before_total = _metric_value(before.text, "agentic_office_transactions_total")

    dispatch = requests.post(
        f"{live_server.base_url}/request",
        json={
            "from_office": "user",
            "to_office": "finance",
            "action": "get_budget",
            "data": {},
        },
        headers=_auth_headers(),
        timeout=10,
    )
    assert dispatch.status_code in (200, 500)

    after = requests.get(
        f"{live_server.base_url}/metrics",
        headers=_auth_headers(),
        timeout=5,
    )
    assert after.status_code == 200
    after_total = _metric_value(after.text, "agentic_office_transactions_total")
    assert after_total >= before_total + 1
