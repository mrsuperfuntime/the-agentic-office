import importlib.util
import os
import tempfile
import uuid
from pathlib import Path

import pytest

pytest_plugins = ("pytest_asyncio",)

MODULE_PATH = Path(__file__).resolve().parents[1] / "main.py"
TEST_DB_PATH = Path(tempfile.gettempdir()) / f"agentic_orchestrator_test_{uuid.uuid4().hex}.db"

os.environ["ORCHESTRATOR_API_KEY"] = "test-key"
os.environ["DATABASE_URL"] = f"sqlite:///{TEST_DB_PATH.as_posix()}"
os.environ["ORCHESTRATOR_MESSAGE_RATE_LIMIT"] = "1000"
os.environ["ORCHESTRATOR_DISPATCH_RATE_LIMIT"] = "1000"
os.environ["ORCHESTRATOR_REQUEST_RATE_LIMIT"] = "1000"
os.environ["ORCHESTRATOR_RATE_WINDOW_SECONDS"] = "60"


def _load_module():
    spec = importlib.util.spec_from_file_location("office_orchestrator_main", str(MODULE_PATH))
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="session")
def orchestrator_module():
    return _load_module()


@pytest.fixture(autouse=True)
def reset_state(orchestrator_module):
    with orchestrator_module.SessionLocal() as session:
        session.query(orchestrator_module.TransactionRecord).delete()
        session.commit()
    with orchestrator_module._rate_lock:
        orchestrator_module._rate_buckets.clear()


@pytest.fixture
def auth_key():
    return "test-key"


@pytest.fixture(scope="session", autouse=True)
def cleanup_test_db():
    yield
    try:
        TEST_DB_PATH.unlink(missing_ok=True)
    except Exception:
        pass
