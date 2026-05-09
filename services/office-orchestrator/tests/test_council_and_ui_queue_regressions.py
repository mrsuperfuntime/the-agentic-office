from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest


class FakeResponse:
    def __init__(self, status_code, payload=None):
        self.status_code = status_code
        self._payload = payload or {}
        self.headers = {"content-type": "application/json"}
        self.text = ""

    def json(self):
        return self._payload


@pytest.mark.asyncio
async def test_beta_and_gamma_council_payloads_present_in_message_responses(orchestrator_module, auth_key):
    async def mock_post_workflow(url, json=None, timeout=60.0):
        if url.endswith("/handle-request"):
            target = (json or {}).get("to_office") or "unknown"
            return FakeResponse(200, {"status": "success", "data": {"response": f"ok:{target}"}})
        return FakeResponse(404, {"status": "error"})

    mock_client_instance = AsyncMock()
    mock_client_instance.post = mock_post_workflow
    mock_client_instance.__aenter__ = AsyncMock(return_value=mock_client_instance)
    mock_client_instance.__aexit__ = AsyncMock(return_value=False)

    with patch.object(orchestrator_module.httpx, "AsyncClient", return_value=mock_client_instance):
        beta_response = await orchestrator_module.message_office(
            {
                "from_office": "user",
                "to_office": "sales",
                "instruction": "Review launch pricing, staffing risk, and integration readiness for next-quarter customer rollout.",
            },
            auth_key,
        )
        gamma_response = await orchestrator_module.message_office(
            {
                "from_office": "user",
                "to_office": "procurement",
                "instruction": "Coordinate suppliers, production readiness, customer handoff, and launch messaging for rollout execution.",
            },
            auth_key,
        )

    beta_council = (beta_response.get("response") or {}).get("ceo_review_council")
    gamma_council = (gamma_response.get("response") or {}).get("ceo_operations_council")

    assert beta_council and beta_council.get("enabled") is True
    assert beta_council.get("owner_office") == "sales"
    assert any(item.get("office") == "finance" for item in beta_council.get("collaborators", []))

    assert gamma_council and gamma_council.get("enabled") is True
    assert gamma_council.get("owner_office") == "procurement"
    assert any(item.get("office") == "manufacturing" for item in gamma_council.get("collaborators", []))


def test_ui_queue_insertion_logic_bound_to_message_response_payloads():
    index_path = Path(__file__).resolve().parents[1] / "static" / "index.html"
    html = index_path.read_text(encoding="utf-8")

    assert "const autoReview = officeResponse.auto_research_review || null;" in html
    assert "addFloor3ReviewPacket(autoPacket);" in html
    assert "else if (betaCouncil && betaCouncil.enabled)" in html
    assert "source: 'council_payload_fallback'" in html

    assert "const gammaCouncil = (payload.response || {}).ceo_operations_council || null;" in html
    assert "if (gammaCouncil && gammaCouncil.enabled)" in html
    assert "addGammaCouncilItem(gammaItem);" in html


@pytest.mark.asyncio
async def test_integrations_status_degraded_contract_when_it_unreachable(orchestrator_module):
    async def mock_get_fail(_url, timeout=10.0):
        raise RuntimeError("IT office unavailable")

    mock_client_instance = AsyncMock()
    mock_client_instance.get = mock_get_fail
    mock_client_instance.__aenter__ = AsyncMock(return_value=mock_client_instance)
    mock_client_instance.__aexit__ = AsyncMock(return_value=False)

    with patch.object(orchestrator_module.httpx, "AsyncClient", return_value=mock_client_instance):
        payload = await orchestrator_module.get_integration_status()

    assert payload["status"] == "degraded"
    assert payload["connections"] == []
    assert payload["linked_count"] == 0
    assert payload["catalog_count"] == 0
    assert isinstance(payload.get("errors"), list)
    assert payload["errors"]
    assert "Failed to reach IT office" in payload["errors"][0]
