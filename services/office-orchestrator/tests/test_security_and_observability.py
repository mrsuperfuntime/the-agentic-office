import json
import os
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException


def test_require_api_key_accepts_valid_key(orchestrator_module, auth_key):
    result = orchestrator_module.require_api_key(auth_key)
    assert result == auth_key


def test_require_api_key_rejects_missing(orchestrator_module):
    with pytest.raises(HTTPException) as exc:
        orchestrator_module.require_api_key(None)
    assert exc.value.status_code == 401


def test_require_api_key_rejects_invalid(orchestrator_module):
    with pytest.raises(HTTPException) as exc:
        orchestrator_module.require_api_key("wrong-key")
    assert exc.value.status_code == 401


def _latest_json_log(caplog, event_name: str) -> dict:
    for record in reversed(caplog.records):
        try:
            payload = json.loads(record.getMessage())
        except json.JSONDecodeError:
            continue
        if payload.get("event") == event_name:
            return payload
    raise AssertionError(f"Log event not found: {event_name}")


def test_auth_failure_log_schema(orchestrator_module, caplog):
    caplog.set_level("WARNING", logger="orchestrator")

    with pytest.raises(HTTPException):
        orchestrator_module.require_api_key(None)

    payload = _latest_json_log(caplog, "auth_failed")
    assert payload["service"] == "office-orchestrator"
    assert payload["reason"] == "invalid_or_missing_api_key"
    assert "timestamp" in payload


def test_non_dev_rejects_weak_api_key_on_startup():
    module_path = Path(__file__).resolve().parents[1] / "main.py"
    import_snippet = (
        "import importlib.util; "
        f"spec=importlib.util.spec_from_file_location('orchestrator_main_test', r'{module_path.as_posix()}'); "
        "module=importlib.util.module_from_spec(spec); "
        "spec.loader.exec_module(module)"
    )

    env = os.environ.copy()
    env.update(
        {
            "ENVIRONMENT": "production",
            "ORCHESTRATOR_API_KEY": "agentic-office-dev-key",
            "ORCHESTRATOR_CORS_ALLOWED_ORIGINS": "https://example.com",
            "DATABASE_URL": "sqlite:///:memory:",
        }
    )

    result = subprocess.run(
        [sys.executable, "-c", import_snippet],
        capture_output=True,
        text=True,
        env=env,
    )

    assert result.returncode != 0
    combined = (result.stderr or "") + (result.stdout or "")
    assert "ORCHESTRATOR_API_KEY is too weak for non-dev environments" in combined


def test_non_dev_rejects_missing_cors_origins_on_startup():
    module_path = Path(__file__).resolve().parents[1] / "main.py"
    import_snippet = (
        "import importlib.util; "
        f"spec=importlib.util.spec_from_file_location('orchestrator_main_test', r'{module_path.as_posix()}'); "
        "module=importlib.util.module_from_spec(spec); "
        "spec.loader.exec_module(module)"
    )

    env = os.environ.copy()
    env.update(
        {
            "ENVIRONMENT": "production",
            "ORCHESTRATOR_API_KEY": "this-is-a-very-strong-prod-api-key-12345",
            "ORCHESTRATOR_CORS_ALLOWED_ORIGINS": "",
            "DATABASE_URL": "sqlite:///:memory:",
        }
    )

    result = subprocess.run(
        [sys.executable, "-c", import_snippet],
        capture_output=True,
        text=True,
        env=env,
    )

    assert result.returncode != 0
    combined = (result.stderr or "") + (result.stdout or "")
    assert "ORCHESTRATOR_CORS_ALLOWED_ORIGINS must be set in non-dev environments" in combined


def test_rate_limit_blocks_after_threshold(orchestrator_module):
    endpoint = "message"
    identity = "test-identity"
    limit = 2
    window_seconds = 60

    orchestrator_module._enforce_rate_limit(endpoint, identity, limit, window_seconds)
    orchestrator_module._enforce_rate_limit(endpoint, identity, limit, window_seconds)

    with pytest.raises(HTTPException) as exc:
        orchestrator_module._enforce_rate_limit(endpoint, identity, limit, window_seconds)
    assert exc.value.status_code == 429


def test_rate_limit_log_schema(orchestrator_module, caplog):
    endpoint = "message"
    identity = "schema-test"
    limit = 1

    caplog.set_level("WARNING", logger="orchestrator")
    orchestrator_module._enforce_rate_limit(endpoint, identity, limit, 60)

    with pytest.raises(HTTPException):
        orchestrator_module._enforce_rate_limit(endpoint, identity, limit, 60)

    payload = _latest_json_log(caplog, "rate_limit_exceeded")
    assert payload["endpoint"] == endpoint
    assert payload["identity"] == identity
    assert payload["limit"] == limit
    assert payload["current_count"] >= 1
    assert "timestamp" in payload


def test_rate_limit_sliding_window_expires(orchestrator_module):
    endpoint = "dispatch-log"
    identity = "window-test"
    bucket_key = f"{endpoint}:{identity}"

    with orchestrator_module._rate_lock:
        orchestrator_module._rate_buckets[bucket_key].append(datetime.utcnow() - timedelta(seconds=70))

    # Should not raise because the stale event is outside the 60 second window.
    orchestrator_module._enforce_rate_limit(endpoint, identity, limit=1, window_seconds=60)


@pytest.mark.asyncio
async def test_stats_aggregation(orchestrator_module, auth_key):
    orchestrator_module._append_transaction(
        {
            "action": "message",
            "to_office": "finance",
            "status": "completed",
            "escalated": False,
        }
    )
    orchestrator_module._append_transaction(
        {
            "action": "message",
            "to_office": "sales",
            "status": "failed",
            "escalated": True,
        }
    )
    orchestrator_module._append_transaction(
        {
            "action": "request",
            "to_office": "hr",
            "status": "error",
            "escalated": False,
        }
    )

    stats = await orchestrator_module.get_stats(auth_key)

    assert stats["total_transactions"] == 3
    assert stats["message_transactions"] == 2
    assert stats["by_status"]["completed"] == 1
    assert stats["by_status"]["failed"] == 1
    assert stats["by_status"]["error"] == 1
    assert stats["escalated_count"] == 1
    assert stats["by_office"]["finance"] == 1
    assert stats["by_office"]["sales"] == 1
    assert stats["rate_limits"]["message"] == orchestrator_module.MESSAGE_RATE_LIMIT


@pytest.mark.asyncio
async def test_dispatch_log_schema(orchestrator_module, auth_key, caplog):
    class FakeResponse:
        def __init__(self, status_code, payload=None):
            self.status_code = status_code
            self._payload = payload or {}
            self.headers = {"content-type": "application/json"}

        def json(self):
            return self._payload

    async def mock_post(url, json=None, timeout=60.0):
        if "finance-office" in url:
            return FakeResponse(200, {"status": "success", "data": {"response": "ok"}})
        return FakeResponse(404, {"status": "error"})

    mock_client = AsyncMock()
    mock_client.post = mock_post
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    caplog.set_level("INFO", logger="orchestrator")

    with patch.object(orchestrator_module.httpx, "AsyncClient", return_value=mock_client):
        response = await orchestrator_module.message_office(
            {
                "to_office": "finance",
                "instruction": "validate logging schema",
            },
            auth_key,
        )

    assert response["status"] == "completed"

    payload = _latest_json_log(caplog, "dispatch_completed")
    assert payload["service"] == "office-orchestrator"
    assert payload["to_office"] == "finance"
    assert payload["final_status"] == "completed"
    assert payload["status_code"] == 200
    assert "correlation_id" in payload
