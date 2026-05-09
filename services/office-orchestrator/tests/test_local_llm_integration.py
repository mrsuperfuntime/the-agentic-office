import os
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import pytest
import requests


ORCHESTRATOR_DIR = Path(__file__).resolve().parents[1]
REPO_ROOT = ORCHESTRATOR_DIR.parents[1]
FINANCE_DIR = REPO_ROOT / "services" / "finance-office"


@pytest.mark.integration
def test_local_ollama_integration_generates_non_empty_response():
    if os.getenv("RUN_LOCAL_LLM_INTEGRATION") != "1":
        pytest.skip("Set RUN_LOCAL_LLM_INTEGRATION=1 to run local Ollama integration test")

    ollama_url = os.getenv("OLLAMA_URL", "http://127.0.0.1:11434")
    ollama_model = os.getenv("OLLAMA_MODEL", "mistral")

    if not _ollama_model_available(ollama_url, ollama_model):
        pytest.skip(f"Ollama model '{ollama_model}' not available at {ollama_url}")

    work_dir = Path(tempfile.mkdtemp(prefix="agentic_local_llm_"))
    db_path = work_dir / "orchestrator_llm.db"

    finance_port = _free_port()
    orchestrator_port = _free_port()

    finance_proc = None
    orchestrator_proc = None

    try:
        finance_proc = _start_finance_service(finance_port, ollama_url, ollama_model)
        _wait_for_health(f"http://127.0.0.1:{finance_port}/health")

        manager = requests.get(f"http://127.0.0.1:{finance_port}/manager", timeout=10)
        assert manager.status_code == 200, manager.text
        llm_status = manager.json().get("llm_status", {})
        assert llm_status.get("primary") == "ollama"
        assert llm_status.get("strict_local") is True
        assert "ollama" in llm_status.get("available_providers", [])

        orchestrator_proc = _start_orchestrator(
            orchestrator_port,
            db_path,
            office_url_overrides={"finance": f"http://127.0.0.1:{finance_port}"},
            ollama_url=ollama_url,
            ollama_model=ollama_model,
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
                "instruction": "Summarize Q2 cashflow risks in three concise bullet points.",
            },
            timeout=90,
        )
        assert dispatch.status_code == 200, dispatch.text

        payload = dispatch.json()
        office_response = payload.get("response") or {}
        text = ((office_response.get("data") or {}).get("response") or office_response.get("response") or "").strip()

        assert payload.get("status") == "completed"
        assert text != ""
        assert not text.lower().startswith("error")
    finally:
        _stop_process(orchestrator_proc)
        _stop_process(finance_proc)


def _ollama_model_available(ollama_url: str, ollama_model: str) -> bool:
    try:
        response = requests.get(f"{ollama_url}/api/tags", timeout=5)
    except requests.RequestException:
        return False

    if response.status_code != 200:
        return False

    models = [entry.get("name", "") for entry in response.json().get("models", [])]
    return any(name == ollama_model or name.startswith(f"{ollama_model}:") for name in models)


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def _wait_for_health(url: str, timeout_seconds: float = 40.0) -> None:
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        try:
            response = requests.get(url, timeout=1.0)
            if response.status_code == 200:
                return
        except requests.RequestException:
            pass
        time.sleep(0.3)
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


def _start_finance_service(port: int, ollama_url: str, ollama_model: str) -> subprocess.Popen:
    env = os.environ.copy()
    env["PYTHONPATH"] = str(REPO_ROOT)
    env["LLM_STRICT_LOCAL"] = "true"
    env["LLM_PRIMARY_PROVIDER"] = "ollama"
    env["LLM_FALLBACK_PROVIDER"] = "groq"
    env["LLM_ENABLE_FALLBACK"] = "false"
    env["OLLAMA_URL"] = ollama_url
    env["OLLAMA_MODEL"] = ollama_model

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


def _start_orchestrator(
    port: int,
    db_path: Path,
    office_url_overrides: dict | None,
    ollama_url: str,
    ollama_model: str,
) -> subprocess.Popen:
    env = os.environ.copy()
    env["ORCHESTRATOR_API_KEY"] = "local-smoke-key"
    env["DATABASE_URL"] = f"sqlite:///{db_path.as_posix()}"
    env["ORCHESTRATOR_MESSAGE_RATE_LIMIT"] = "50"
    env["ORCHESTRATOR_DISPATCH_RATE_LIMIT"] = "100"
    env["ORCHESTRATOR_REQUEST_RATE_LIMIT"] = "100"
    env["ORCHESTRATOR_RATE_WINDOW_SECONDS"] = "60"
    env["LLM_STRICT_LOCAL"] = "true"
    env["LLM_PRIMARY_PROVIDER"] = "ollama"
    env["LLM_FALLBACK_PROVIDER"] = "groq"
    env["LLM_ENABLE_FALLBACK"] = "false"
    env["OLLAMA_URL"] = ollama_url
    env["OLLAMA_MODEL"] = ollama_model

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
