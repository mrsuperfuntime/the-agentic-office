import pytest
from unittest.mock import AsyncMock, patch
from fastapi import HTTPException


class FakeResponse:
    def __init__(self, status_code, payload=None):
        self.status_code = status_code
        self._payload = payload or {}
        self.headers = {"content-type": "application/json"}
        self.text = ""

    def json(self):
        return self._payload


def test_routing_confidence(orchestrator_module):
    """Test routing confidence scoring with keyword matching."""
    office, reason, confidence, keywords = orchestrator_module.route_task_to_office(
        "Review the budget forecast, cost model, and cash outlook."
    )

    assert office == "finance"
    assert "Matched task keywords" in reason
    assert confidence > 0.35
    assert "budget" in keywords
    assert len(keywords) >= 2


def test_routing_to_it_for_integration_keywords(orchestrator_module):
    """Integration setup requests should auto-route to IT office."""
    office, reason, confidence, keywords = orchestrator_module.route_task_to_office(
        "Link X and Instagram integrations with oauth tokens and API credential references."
    )

    assert office == "it"
    assert "Matched task keywords" in reason
    assert confidence > 0.3
    assert any(keyword in keywords for keyword in ["integration", "instagram", "api", "oauth"])


def test_routing_to_it_for_meshy_keywords(orchestrator_module):
    office, reason, confidence, keywords = orchestrator_module.route_task_to_office(
        "Connect Meshy AI API using a secure credential reference for creative asset generation."
    )

    assert office == "it"
    assert "Matched task keywords" in reason
    assert confidence > 0.3
    assert any(keyword in keywords for keyword in ["api", "meshy", "credential", "connect"])


def test_social_media_quick_post_policy_selected(orchestrator_module):
    policy_id, roles, requires_final_approval = orchestrator_module._build_workflow_roles(
        "social-media",
        "Quick post for X about our launch today.",
    )

    assert policy_id == "social-media-quick-post"
    assert [role["name"] for role in roles] == ["creator", "integration-reviewer"]
    assert requires_final_approval is False


def test_it_3d_meshy_policy_selected(orchestrator_module):
    policy_id, roles, requires_final_approval = orchestrator_module._build_workflow_roles(
        "it",
        "Generate a 3D mascot model using Meshy with a GLB output.",
    )

    assert policy_id == "it-3d-meshy-generation"
    assert [role["name"] for role in roles] == ["creator", "reviewer", "approver"]
    assert roles[0]["office"] == "it"
    assert roles[1]["office"] == "manufacturing"
    assert requires_final_approval is True


def test_ceo_review_council_policy_selected_for_sales(orchestrator_module):
    policy_id, roles, requires_final_approval = orchestrator_module._build_workflow_roles(
        "sales",
        "Review launch pricing, hiring support, and integration readiness for the new customer rollout.",
    )

    assert policy_id == "ceo-review-council"
    assert [role["office"] for role in roles] == ["sales", "finance", "hr", "it"]
    assert requires_final_approval is False


@pytest.mark.asyncio
async def test_fallback_escalation_on_primary_failure(orchestrator_module, auth_key):
    """Test that primary office failure triggers fallback to secondary office."""

    async def mock_post_with_fallback(url, json=None, timeout=60.0):
        if "sales-office" in url:
            return FakeResponse(500, {"status": "error", "message": "primary unavailable"})
        if "finance-office" in url:
            return FakeResponse(200, {"status": "success", "data": {"response": "fallback success"}})
        return FakeResponse(404, {"status": "error"})

    mock_client_instance = AsyncMock()
    mock_client_instance.post = mock_post_with_fallback
    mock_client_instance.__aenter__ = AsyncMock(return_value=mock_client_instance)
    mock_client_instance.__aexit__ = AsyncMock(return_value=False)

    with patch.object(orchestrator_module.httpx, "AsyncClient", return_value=mock_client_instance):
        response = await orchestrator_module.message_office(
            {
                "from_office": "user",
                "to_office": "sales",
                "instruction": "Run a revenue health check",
            },
            auth_key,
        )

    assert response["escalated"] is True
    assert response["to_office"] == "finance"
    assert response["status"] == "completed"

    logs = orchestrator_module._get_transactions(action="message")
    assert len(logs) == 1
    assert len(logs[0]["attempts"]) == 2
    assert logs[0]["attempts"][0]["office"] == "sales"
    assert logs[0]["attempts"][1]["office"] == "finance"


@pytest.mark.asyncio
async def test_ceo_review_council_context_is_attached_to_stage_requests(orchestrator_module, auth_key):
    captured_requests = []

    async def mock_post_council(url, json=None, timeout=60.0):
        if url.endswith("/handle-request"):
            captured_requests.append({"url": url, "json": json})
            return FakeResponse(200, {"status": "success", "data": {"response": f"ok:{json.get('to_office')}"}})
        return FakeResponse(404, {"status": "error"})

    mock_client_instance = AsyncMock()
    mock_client_instance.post = mock_post_council
    mock_client_instance.__aenter__ = AsyncMock(return_value=mock_client_instance)
    mock_client_instance.__aexit__ = AsyncMock(return_value=False)

    with patch.object(orchestrator_module.httpx, "AsyncClient", return_value=mock_client_instance):
        response = await orchestrator_module.message_office(
            {
                "from_office": "user",
                "to_office": "sales",
                "instruction": "Review launch pricing, hiring support, integration readiness, and publish rollout follow-ups for the new offer.",
            },
            auth_key,
        )

    assert response["status"] == "completed"
    assert len(captured_requests) == 4
    council = response["response"]["ceo_review_council"]
    assert council["bidirectional"] is True
    assert {item["office"] for item in council["collaborators"]} == {"sales", "finance", "hr", "it"}
    assert any(item["office"] == "social-media" for item in council["fulfillment_targets"])

    first_payload = captured_requests[0]["json"]
    assert first_payload["data"]["ceo_review_council"]["bidirectional"] is True
    assert first_payload["data"]["ceo_review_council"]["owner_office"] == "sales"


@pytest.mark.asyncio
async def test_dispatch_log_filters(orchestrator_module, auth_key):
    """Test dispatch-log filtering by office and status."""

    async def mock_post_dispatch(url, json=None, timeout=60.0):
        instruction = (json or {}).get("instruction", "")
        if "fail" in instruction:
            return FakeResponse(400, {"status": "error", "data": {"response": "failed request"}})
        return FakeResponse(200, {"status": "success", "data": {"response": "ok"}})

    mock_client_instance = AsyncMock()
    mock_client_instance.post = mock_post_dispatch
    mock_client_instance.__aenter__ = AsyncMock(return_value=mock_client_instance)
    mock_client_instance.__aexit__ = AsyncMock(return_value=False)

    with patch.object(orchestrator_module.httpx, "AsyncClient", return_value=mock_client_instance):
        await orchestrator_module.message_office(
            {"to_office": "finance", "instruction": "finance success message"},
            auth_key,
        )
        await orchestrator_module.message_office(
            {"to_office": "finance", "instruction": "finance fail message"},
            auth_key,
        )
        await orchestrator_module.message_office(
            {"to_office": "sales", "instruction": "sales success message"},
            auth_key,
        )

    logs_all = orchestrator_module._get_transactions(action="message")
    assert len(logs_all) == 3

    logs_finance_completed = orchestrator_module._get_transactions(
        action="message", office="finance", status="completed"
    )
    assert len(logs_finance_completed) == 1
    assert logs_finance_completed[0]["to_office"] == "finance"
    assert logs_finance_completed[0]["status"] == "completed"

    logs_limited = orchestrator_module._get_transactions(limit=2, action="message")
    assert len(logs_limited) == 2


@pytest.mark.asyncio
async def test_social_media_workflow_uses_creator_reviewer_and_coordinator_approval(orchestrator_module, auth_key):
    """Social-media work should run through creator, HR reviewer, and coordinator approval roles."""

    async def mock_post_workflow(url, json=None, timeout=60.0):
        if "social-media-office" in url:
            return FakeResponse(200, {"status": "success", "data": {"response": "draft created"}})
        if "hr-office" in url:
            return FakeResponse(200, {"status": "success", "data": {"response": "policy review complete"}})
        if "it-office" in url:
            return FakeResponse(200, {"status": "success", "data": {"ready_platforms": ["linkedin"], "response": "integration validated"}})
        return FakeResponse(404, {"status": "error"})

    mock_client_instance = AsyncMock()
    mock_client_instance.post = mock_post_workflow
    mock_client_instance.__aenter__ = AsyncMock(return_value=mock_client_instance)
    mock_client_instance.__aexit__ = AsyncMock(return_value=False)

    with patch.object(orchestrator_module.httpx, "AsyncClient", return_value=mock_client_instance):
        response = await orchestrator_module.message_office(
            {
                "from_office": "user",
                "to_office": "social-media",
                "instruction": "Create a LinkedIn launch post for our internship program and include brand-safe language.",
            },
            auth_key,
        )

    assert response["status"] == "needs_final_approval"
    assert response["to_office"] == "social-media"
    assert response["response"]["final_approval"]["required"] is True
    assert response["response"]["final_approval"]["queue_state"] == "pending"

    attempts = response["attempts"]
    assert len(attempts) == 4
    assert attempts[0]["role"] == "creator"
    assert attempts[0]["office"] == "social-media"
    assert attempts[1]["role"] == "reviewer"
    assert attempts[1]["office"] == "hr"
    assert attempts[2]["role"] == "integration-reviewer"
    assert attempts[2]["office"] == "it"
    assert attempts[3]["role"] == "approver"
    assert attempts[3]["office"] == "orchestrator"
    assert attempts[3]["status_code"] == 200


@pytest.mark.asyncio
async def test_procurement_workflow_uses_creator_reviewer_and_needs_final_approval(orchestrator_module, auth_key):
    async def mock_post_workflow(url, json=None, timeout=60.0):
        if "procurement-office" in url:
            return FakeResponse(200, {"status": "success", "data": {"response": "vendors shortlisted"}})
        if "finance-office" in url:
            return FakeResponse(200, {"status": "success", "data": {"response": "budget check passed"}})
        return FakeResponse(404, {"status": "error"})

    mock_client_instance = AsyncMock()
    mock_client_instance.post = mock_post_workflow
    mock_client_instance.__aenter__ = AsyncMock(return_value=mock_client_instance)
    mock_client_instance.__aexit__ = AsyncMock(return_value=False)

    with patch.object(orchestrator_module.httpx, "AsyncClient", return_value=mock_client_instance):
        response = await orchestrator_module.message_office(
            {
                "from_office": "user",
                "to_office": "procurement",
                "instruction": "Prepare a supplier shortlist for laptop procurement with pricing rationale.",
            },
            auth_key,
        )

    assert response["status"] == "needs_final_approval"
    assert [attempt["role"] for attempt in response["attempts"]] == ["creator", "reviewer", "approver"]
    assert response["attempts"][0]["office"] == "procurement"
    assert response["attempts"][1]["office"] == "finance"


@pytest.mark.asyncio
async def test_hiring_workflow_uses_strict_hr_finance_and_needs_final_approval(orchestrator_module, auth_key):
    async def mock_post_workflow(url, json=None, timeout=60.0):
        if "hr-office" in url:
            return FakeResponse(200, {"status": "success", "data": {"response": "candidate slate prepared"}})
        if "finance-office" in url:
            return FakeResponse(200, {"status": "success", "data": {"response": "headcount budget approved"}})
        return FakeResponse(404, {"status": "error"})

    mock_client_instance = AsyncMock()
    mock_client_instance.post = mock_post_workflow
    mock_client_instance.__aenter__ = AsyncMock(return_value=mock_client_instance)
    mock_client_instance.__aexit__ = AsyncMock(return_value=False)

    with patch.object(orchestrator_module.httpx, "AsyncClient", return_value=mock_client_instance):
        response = await orchestrator_module.message_office(
            {
                "from_office": "user",
                "to_office": "hr",
                "instruction": "Hire three backend engineers and schedule interview loops with compensation bands.",
            },
            auth_key,
        )

    assert response["status"] == "needs_final_approval"
    assert [attempt["role"] for attempt in response["attempts"]] == ["creator", "reviewer", "approver"]
    assert response["attempts"][0]["office"] == "hr"
    assert response["attempts"][1]["office"] == "finance"


@pytest.mark.asyncio
async def test_final_approval_queue_requires_explicit_user_approval(orchestrator_module, auth_key):
    async def mock_post_workflow(url, json=None, timeout=60.0):
        if "social-media-office" in url:
            return FakeResponse(
                200,
                {
                    "status": "success",
                    "data": {
                        "response": "draft set ready",
                        "generated_posts": [
                            "Post 1: Launch your career with our internship program.",
                            "Post 2: Build production skills with real mentorship.",
                            "Post 3: Applications are open now.",
                        ],
                    },
                },
            )
        if "hr-office" in url:
            return FakeResponse(200, {"status": "success", "data": {"response": "compliance pass"}})
        if "it-office" in url and url.endswith("/handle-request"):
            return FakeResponse(200, {"status": "success", "data": {"ready_platforms": ["x"], "response": "integration pass"}})
        if "it-office" in url and url.endswith("/publish"):
            return FakeResponse(200, {"status": "success", "published_count": 3, "platforms": ["x"]})
        return FakeResponse(404, {"status": "error"})

    mock_client_instance = AsyncMock()
    mock_client_instance.post = mock_post_workflow
    mock_client_instance.__aenter__ = AsyncMock(return_value=mock_client_instance)
    mock_client_instance.__aexit__ = AsyncMock(return_value=False)

    with patch.object(orchestrator_module.httpx, "AsyncClient", return_value=mock_client_instance):
        queued = await orchestrator_module.message_office(
            {
                "from_office": "user",
                "to_office": "social-media",
                "instruction": "Create 3 launch posts for the internship campaign with voice and hashtag constraints.",
            },
            auth_key,
        )

        assert queued["status"] == "needs_final_approval"

        pending = await orchestrator_module.get_pending_approvals(limit=20, _auth=auth_key)
        queued_item = next((item for item in pending["pending_approvals"] if item["id"] == queued["request_id"]), None)
        assert queued_item is not None

        creator_stage = next(
            (stage for stage in queued_item["office_response"]["workflow"] if stage["role"] == "creator"),
            None,
        )
        assert creator_stage is not None
        assert creator_stage["stage_response"]["data"]["generated_posts"][0].startswith("Post 1:")

        approved = await orchestrator_module.finalize_approval(
            queued["request_id"],
            orchestrator_module.ApprovalActionRequest(approved=True, approver="weveg", notes="Looks good"),
            _auth=auth_key,
        )

    assert approved["status"] == "completed"
    assert approved["publish_result"]["status"] == "success"
    tx = approved["transaction"]
    assert tx["status"] == "completed"
    assert tx["attempts"][-1]["role"] == "final-approver"
    assert tx["attempts"][-1]["status_code"] == 200


@pytest.mark.asyncio
async def test_social_media_workflow_reviewer_stage_is_strict_and_fails_closed(orchestrator_module, auth_key):
    """HR reviewer stage must not fallback to another office for approval-sensitive workflows."""

    async def mock_post_workflow(url, json=None, timeout=60.0):
        if "social-media-office" in url:
            return FakeResponse(200, {"status": "success", "data": {"response": "draft created"}})
        if "hr-office" in url:
            return FakeResponse(500, {"status": "error", "message": "review service unavailable"})
        if "customer-service-office" in url:
            return FakeResponse(200, {"status": "success", "data": {"response": "unexpected fallback"}})
        return FakeResponse(404, {"status": "error"})

    mock_client_instance = AsyncMock()
    mock_client_instance.post = mock_post_workflow
    mock_client_instance.__aenter__ = AsyncMock(return_value=mock_client_instance)
    mock_client_instance.__aexit__ = AsyncMock(return_value=False)

    with patch.object(orchestrator_module.httpx, "AsyncClient", return_value=mock_client_instance):
        with pytest.raises(HTTPException) as exc:
            await orchestrator_module.message_office(
                {
                    "from_office": "user",
                    "to_office": "social-media",
                    "instruction": "Create a compliant intern campaign post with hiring language safeguards.",
                },
                auth_key,
            )

    assert exc.value.status_code == 500
    assert "Workflow stage 'reviewer' failed" in exc.value.detail or "Office hr returned 500" in exc.value.detail

    logs = orchestrator_module._get_transactions(action="message")
    assert len(logs) == 1
    attempts = logs[0]["attempts"]
    assert len(attempts) == 2
    assert attempts[0]["role"] == "creator"
    assert attempts[1]["role"] == "reviewer"
    assert all(attempt["office"] != "customer-service" for attempt in attempts)
