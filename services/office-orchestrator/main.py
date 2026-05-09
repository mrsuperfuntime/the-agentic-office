"""
Office Orchestrator Service
Central management and routing for all office services
"""
import logging
import os
import uuid
import json
import re
from collections import defaultdict, deque
from datetime import datetime, timedelta
from pathlib import Path
from threading import Lock
from urllib.parse import urlsplit

import httpx
from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from sqlalchemy import JSON, Boolean, DateTime, Float, Integer, String, Text, create_engine, desc
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker

logger = logging.getLogger("orchestrator")
logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)


def _log_event(level: int, event: str, **fields) -> None:
    payload = {
        "event": event,
        "service": "office-orchestrator",
        "timestamp": datetime.utcnow().isoformat(),
    }
    payload.update(fields)
    logger.log(level, json.dumps(payload, sort_keys=True))


def _redact_database_url(database_url: str) -> str:
    if database_url.startswith("sqlite"):
        return "sqlite://***"
    parsed = urlsplit(database_url)
    host = parsed.hostname or "unknown"
    db_name = parsed.path.lstrip("/") if parsed.path else ""
    return f"{parsed.scheme}://***@{host}/{db_name}" if db_name else f"{parsed.scheme}://***@{host}"


def _env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.lower() in {"1", "true", "yes", "on"}


def _parse_allowed_origins() -> list[str]:
    raw = os.getenv("ORCHESTRATOR_CORS_ALLOWED_ORIGINS", "http://localhost:8000,http://127.0.0.1:8000")
    origins = [origin.strip() for origin in raw.split(",") if origin.strip()]
    return origins or ["http://localhost:8000", "http://127.0.0.1:8000"]


CORS_ALLOWED_ORIGINS = _parse_allowed_origins()
CORS_ALLOW_CREDENTIALS = _env_bool("ORCHESTRATOR_CORS_ALLOW_CREDENTIALS", True)

ENVIRONMENT = os.getenv("ENVIRONMENT", "development").strip().lower()
IS_NON_DEV_ENV = ENVIRONMENT not in {"dev", "development", "test"}
REQUIRE_METADATA_AUTH = _env_bool("ORCHESTRATOR_REQUIRE_METADATA_AUTH", IS_NON_DEV_ENV)

if IS_NON_DEV_ENV and not os.getenv("ORCHESTRATOR_CORS_ALLOWED_ORIGINS"):
    raise RuntimeError("ORCHESTRATOR_CORS_ALLOWED_ORIGINS must be set in non-dev environments")

if CORS_ALLOW_CREDENTIALS and "*" in CORS_ALLOWED_ORIGINS:
    raise RuntimeError("Invalid CORS config: wildcard origins cannot be combined with credentials")

app = FastAPI(title="Office Orchestrator", version="1.0.0")

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ALLOWED_ORIGINS,
    allow_credentials=CORS_ALLOW_CREDENTIALS,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount static files
static_dir = Path(__file__).parent / "static"
if static_dir.exists():
    app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")


class MessageRequest(BaseModel):
    to_office: str | None = Field(None, description="Target office ID or 'auto' for C-suite routing")
    instruction: str = Field(..., description="Natural language task instruction", min_length=1)
    from_office: str = Field("user", description="Originating office")
    data: dict = Field(default_factory=dict, description="Additional payload data")


class MessageResponse(BaseModel):
    request_id: int
    correlation_id: str
    status: str
    executive_controller: str
    to_office: str
    to_manager: str
    routed_reason: str
    routing_confidence: float
    matched_keywords: list[str]
    escalated: bool
    instruction: str
    response: dict | None = None
    attempts: list[dict] = Field(default_factory=list)


class ApprovalActionRequest(BaseModel):
    approved: bool = Field(True, description="Approve or reject a queued request")
    approver: str = Field("user", description="Final approver identity")
    notes: str | None = Field(default=None, description="Optional decision notes")


class WorkerCreateRequest(BaseModel):
    name: str = Field(..., description="Worker name")
    floor: str = Field("1", description="Floor assignment")
    teams: list[str] = Field(default_factory=list, description="Teams assigned")
    role: str | None = Field(None, description="Worker role/title")
    email: str | None = Field(None, description="Worker email")
    status: str = Field("active", description="Worker status")
    assigned_platforms: list[str] = Field(default_factory=list, description="Platforms assigned")


class WorkerAssignRequest(BaseModel):
    platforms: list[str] = Field(default_factory=list, description="Platforms to assign")
    teams: list[str] = Field(default_factory=list, description="Teams to assign")


class IntegrationCatalogCreateRequest(BaseModel):
    integration: str = Field(..., description="Unique integration id")
    name: str = Field(..., description="Display name")
    aliases: list[str] = Field(default_factory=list, description="Optional aliases")
    category: str = Field("social-platform", description="Integration category")
    publish_capable: bool = Field(True, description="Can be used as a publishing target")
    credential_scope: str = Field("social", description="Credential vault scope")


class IntegrationLinkRequest(BaseModel):
    integration: str = Field(..., description="Integration id")
    account_name: str | None = Field(default=None, description="Account handle or profile name")
    credential_ref: str | None = Field(default=None, description="Vault credential reference")
    connection_method: str | None = Field(default=None, description="Secure connection method")
    scopes: list[str] = Field(default_factory=list, description="Requested OAuth/API scopes")


# Office registry
OFFICES = {
    "sales": "http://sales-office:8000",
    "hr": "http://hr-office:8000",
    "customer-service": "http://customer-service-office:8000",
    "procurement": "http://procurement-office:8000",
    "finance": "http://finance-office:8000",
    "manufacturing": "http://manufacturing-office:8000",
    "social-media": "http://social-media-office:8000",
    "it": "http://it-office:8000",
}


def _office_url_env_key(office_name: str) -> str:
    return f"OFFICE_URL_{office_name.upper().replace('-', '_')}"


OFFICES = {
    office_name: os.getenv(_office_url_env_key(office_name), default_url)
    for office_name, default_url in OFFICES.items()
}

# Executive manager map for routing context
OFFICE_MANAGERS = {
    "sales": "Sales Manager Agent",
    "hr": "HR Director",
    "customer-service": "Customer Experience Director",
    "procurement": "Procurement Director",
    "finance": "Finance Director",
    "manufacturing": "Manufacturing Director",
    "social-media": "Propaganda Director",
    "it": "IT Manager Agent",
}

# Keyword-based routing hints used by the C-suite controller
ROUTING_KEYWORDS = {
    "sales": ["sales", "deal", "pipeline", "revenue", "prospect", "close", "lead",
               "trend", "trending", "signal", "reddit", "etsy", "makerworld", "maker world",
               "youtube trends", "google trends", "leia organa", "research summary", "cost review",
               "hr risk", "offensive", "gross"],
    "hr": ["hiring", "recruit", "candidate", "employee", "payroll", "policy", "benefits", "integrity", "offensive", "gross", "professionalism"],
    "customer-service": ["customer", "ticket", "support", "complaint", "nps", "sla", "issue"],
    "procurement": ["vendor", "purchase", "supplier", "po", "sourcing", "quote", "procurement"],
    "finance": ["budget", "expense", "financial", "forecast", "cost", "investment", "cash", "cost analysis", "roi", "margin"],
    "manufacturing": ["production", "inventory", "factory", "quality", "schedule", "capacity"],
    "social-media": ["post", "social", "campaign", "content", "engagement", "followers", "brand", "publish", "tweet", "twitter", "instagram", "linkedin", "tiktok", "facebook", "snap", "snapchat"],
    "it": ["integration", "oauth", "api", "platform", "token", "credential", "connect", "link", "connector", "meshy", "meshy ai"],
}

FALLBACK_OFFICE = {
    "sales": "finance",
    "finance": "sales",
    "hr": "customer-service",
    "customer-service": "hr",
    "procurement": "manufacturing",
    "manufacturing": "procurement",
    "social-media": "sales",
    "it": "customer-service",
}

CEO_REVIEW_COUNCIL_OFFICES = {
    "sales": {
        "label": "commercial",
        "purpose": "Validate demand, market timing, customer impact, and go-to-market assumptions.",
        "keywords": ["sales", "deal", "pipeline", "revenue", "customer", "pricing", "launch", "market", "trend", "campaign"],
        "follow_up": "Return demand signals, launch risks, and customer-facing follow-ups to the council.",
    },
    "finance": {
        "label": "financial",
        "purpose": "Review budget impact, spend guardrails, ROI, and funding constraints.",
        "keywords": ["budget", "expense", "financial", "forecast", "cash", "roi", "margin", "pricing", "cost"],
        "follow_up": "Return budget thresholds, funding blockers, and fiscal next steps to the council.",
    },
    "hr": {
        "label": "people",
        "purpose": "Review hiring, staffing, policy, professionalism, and organizational change risk.",
        "keywords": ["hire", "hiring", "headcount", "employee", "staff", "policy", "compliance", "training", "integrity"],
        "follow_up": "Return staffing constraints, policy actions, and people-risk follow-ups to the council.",
    },
    "it": {
        "label": "technical",
        "purpose": "Review platform readiness, security, integrations, systems dependencies, and delivery risk.",
        "keywords": ["integration", "api", "oauth", "security", "platform", "system", "automation", "deploy", "credential", "infrastructure"],
        "follow_up": "Return integration blockers, security actions, and implementation dependencies to the council.",
    },
}

CEO_REVIEW_DEFAULT_PEERS = {
    "sales": ["finance", "hr"],
    "finance": ["sales", "hr"],
    "hr": ["finance", "it"],
    "it": ["finance", "hr"],
}

GAMMA_COUNCIL_OFFICES = {
    "procurement": {
        "label": "sourcing",
        "purpose": "Execute vendor selection, supplier relations, lead-time coordination, and cost oversight.",
        "keywords": ["vendor", "purchase", "supplier", "quote", "contract", "sourcing", "logistics", "fulfillment"],
        "follow_up": "Return vendor blockers, lead-time constraints, and fulfillment status to the council.",
    },
    "manufacturing": {
        "label": "production",
        "purpose": "Execute production planning, quality assurance, inventory management, and operational efficiency.",
        "keywords": ["production", "inventory", "factory", "capacity", "quality", "manufacturing", "fulfillment", "throughput"],
        "follow_up": "Return production readiness, throughput constraints, and quality follow-ups to the council.",
    },
    "customer-service": {
        "label": "feedback",
        "purpose": "Execute customer support, success tracking, feedback analysis, and satisfaction monitoring.",
        "keywords": ["customer", "support", "onboard", "ticket", "rollout", "enablement", "feedback", "escalation"],
        "follow_up": "Return customer impact, escalation risks, and voice-of-customer follow-ups to the council.",
    },
    "social-media": {
        "label": "propaganda",
        "purpose": "Execute content operations, community signals, publishing coordination, and outward messaging.",
        "keywords": ["campaign", "post", "publish", "content", "launch", "announcement", "messaging", "propaganda"],
        "follow_up": "Return messaging blockers, publishing delays, and campaign response loops to the council.",
    },
}

GAMMA_COUNCIL_DEFAULT_PEERS = {
    "procurement": ["manufacturing", "customer-service"],
    "manufacturing": ["procurement", "customer-service"],
    "customer-service": ["procurement", "manufacturing"],
    "social-media": ["procurement", "manufacturing", "customer-service"],
}

FULFILLMENT_SCOPE_RULES = {
    "social-media": {
        "keywords": ["campaign", "post", "publish", "content", "launch", "announcement"],
        "purpose": "Publish approved messaging and run channel execution.",
    },
    "procurement": {
        "keywords": ["vendor", "purchase", "supplier", "quote", "contract", "sourcing"],
        "purpose": "Execute sourcing, vendor outreach, and purchasing follow-through.",
    },
    "manufacturing": {
        "keywords": ["production", "inventory", "factory", "capacity", "quality", "manufacturing"],
        "purpose": "Execute production planning, capacity checks, and operational fulfillment.",
    },
    "customer-service": {
        "keywords": ["customer", "support", "onboard", "ticket", "rollout", "enablement"],
        "purpose": "Handle rollout support, customer follow-up, and fulfillment feedback loops.",
    },
}

WORKFLOW_POLICIES = {
    "social-media-quick-post": {
        "office": "social-media",
        "trigger_keywords": ["quick post", "single post", "one post", "tweet", "x post", "ship this post"],
        "requires_final_user_approval": False,
        "roles": [
            {
                "name": "creator",
                "office": "social-media",
                "manager": "Social Media Manager Agent",
                "requires_remote": True,
                "allow_fallback": False,
            },
            {
                "name": "integration-reviewer",
                "office": "it",
                "manager": "IT Manager Agent",
                "requires_remote": True,
                "allow_fallback": False,
            },
        ],
    },
    "social-media-campaign-orchestration": {
        "office": "social-media",
        "trigger_keywords": ["content calendar", "multi-platform", "cross-channel", "weekly series", "launch week", "campaign sprint"],
        "requires_final_user_approval": True,
        "roles": [
            {
                "name": "strategist",
                "office": "sales",
                "manager": "Sales Manager Agent",
                "requires_remote": True,
                "allow_fallback": False,
            },
            {
                "name": "creator",
                "office": "social-media",
                "manager": "Social Media Manager Agent",
                "requires_remote": True,
                "allow_fallback": False,
            },
            {
                "name": "reviewer",
                "office": "hr",
                "manager": "HR Manager Agent",
                "requires_remote": True,
                "allow_fallback": False,
            },
            {
                "name": "integration-reviewer",
                "office": "it",
                "manager": "IT Manager Agent",
                "requires_remote": True,
                "allow_fallback": False,
            },
            {
                "name": "approver",
                "office": "orchestrator",
                "manager": "Office Orchestrator (C-suite)",
                "requires_remote": False,
            },
        ],
    },
    "social-media-publish": {
        "office": "social-media",
        "trigger_keywords": [],
        "requires_final_user_approval": True,
        "roles": [
            {
                "name": "creator",
                "office": "social-media",
                "manager": "Social Media Manager Agent",
                "requires_remote": True,
                "allow_fallback": False,
            },
            {
                "name": "reviewer",
                "office": "hr",
                "manager": "HR Manager Agent",
                "requires_remote": True,
                "allow_fallback": False,
            },
            {
                "name": "integration-reviewer",
                "office": "it",
                "manager": "IT Manager Agent",
                "requires_remote": True,
                "allow_fallback": False,
            },
            {
                "name": "approver",
                "office": "orchestrator",
                "manager": "Office Orchestrator (C-suite)",
                "requires_remote": False,
            },
        ],
    },
    "it-3d-meshy-generation": {
        "office": "it",
        "trigger_keywords": ["3d", "meshy", "meshy ai", "render", ".glb", ".obj", "model generation"],
        "requires_final_user_approval": True,
        "roles": [
            {
                "name": "creator",
                "office": "it",
                "manager": "IT Manager Agent",
                "requires_remote": True,
                "allow_fallback": False,
            },
            {
                "name": "reviewer",
                "office": "manufacturing",
                "manager": "Manufacturing Manager Agent",
                "requires_remote": True,
                "allow_fallback": False,
            },
            {
                "name": "approver",
                "office": "orchestrator",
                "manager": "Office Orchestrator (C-suite)",
                "requires_remote": False,
            },
        ],
    },
    "it-shenanigans-lab": {
        "office": "it",
        "trigger_keywords": ["shenanigan", "shenanigans", "weird", "chaos mode", "meme experiment", "go wild"],
        "requires_final_user_approval": False,
        "roles": [
            {
                "name": "creator",
                "office": "it",
                "manager": "IT Manager Agent",
                "requires_remote": True,
                "allow_fallback": False,
            },
            {
                "name": "reviewer",
                "office": "social-media",
                "manager": "Social Media Manager Agent",
                "requires_remote": True,
                "allow_fallback": False,
            },
        ],
    },
    "procurement-purchase": {
        "office": "procurement",
        "trigger_keywords": [],
        "requires_final_user_approval": True,
        "roles": [
            {
                "name": "creator",
                "office": "procurement",
                "manager": "Procurement Manager Agent",
                "requires_remote": True,
                "allow_fallback": False,
            },
            {
                "name": "reviewer",
                "office": "finance",
                "manager": "Finance Manager Agent",
                "requires_remote": True,
                "allow_fallback": False,
            },
            {
                "name": "approver",
                "office": "orchestrator",
                "manager": "Office Orchestrator (C-suite)",
                "requires_remote": False,
            },
        ],
    },
    "hr-hiring": {
        "office": "hr",
        "trigger_keywords": ["hire", "hiring", "recruit", "candidate", "headcount", "interview", "job"],
        "requires_final_user_approval": True,
        "roles": [
            {
                "name": "creator",
                "office": "hr",
                "manager": "HR Manager Agent",
                "requires_remote": True,
                "allow_fallback": False,
            },
            {
                "name": "reviewer",
                "office": "finance",
                "manager": "Finance Director",
                "requires_remote": True,
                "allow_fallback": False,
            },
            {
                "name": "approver",
                "office": "orchestrator",
                "manager": "Office Orchestrator (C-suite)",
                "requires_remote": False,
            },
        ],
    },
    "finance-cost-analysis": {
        "office": "finance",
        "trigger_keywords": ["cost analysis", "budget impact", "expense", "spend review", "financial risk", "roi"],
        "requires_final_user_approval": False,
        "roles": [
            {
                "name": "creator",
                "office": "finance",
                "manager": "Finance Director",
                "requires_remote": True,
                "allow_fallback": False,
            },
            {
                "name": "integrity-reviewer",
                "office": "hr",
                "manager": "Integrity Reviewer",
                "requires_remote": True,
                "allow_fallback": False,
            },
        ],
    },
}

OFFICE_CAPABILITIES = {
    "sales": ["analyze-deal", "forecast-revenue", "analyze-prospect", "trend-intelligence", "trend-run", "team-roster", "research-review-routing", "ceo-council-followups", "ceo-council-delegation"],
    "hr": ["evaluate-candidate", "employee-performance", "create-policy", "integrity-review", "hr-sub-agent-orchestration", "ceo-council-followups", "ceo-council-delegation"],
    "customer-service": ["message-triage", "get-open-tickets", "get-satisfaction-score", "customer-service-sub-agent-orchestration", "operations-propaganda-council"],
    "procurement": ["vendor-evaluation", "po-review", "sourcing-plan", "procurement-sub-agent-orchestration", "operations-propaganda-council"],
    "finance": ["analyze-budget", "financial-health", "analyze-expenses", "finance-sub-agent-orchestration", "ceo-council-followups", "ceo-council-delegation"],
    "manufacturing": ["production-plan", "inventory-check", "quality-review", "manufacturing-sub-agent-orchestration", "operations-propaganda-council"],
    "social-media": ["create-content", "content-strategy", "analyze-trends", "store-artifacts", "publish-via-it", "social-propaganda-sub-agent-orchestration", "operations-propaganda-council"],
    "it": ["social-media-integration", "meshy-api-integration", "generate-3d-model", "shenanigans-lab", "link-platform", "list-integrations", "publish-connectors", "token-tracking", "ceo-council-followups", "ceo-council-delegation"],
}

API_KEY = os.getenv("ORCHESTRATOR_API_KEY")
if not API_KEY:
    raise RuntimeError("ORCHESTRATOR_API_KEY must be set")
if IS_NON_DEV_ENV and (API_KEY == "agentic-office-dev-key" or len(API_KEY) < 16):
    raise RuntimeError("ORCHESTRATOR_API_KEY is too weak for non-dev environments")
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./orchestrator.db")

MESSAGE_RATE_LIMIT = int(os.getenv("ORCHESTRATOR_MESSAGE_RATE_LIMIT", "60"))
DISPATCH_RATE_LIMIT = int(os.getenv("ORCHESTRATOR_DISPATCH_RATE_LIMIT", "120"))
REQUEST_RATE_LIMIT = int(os.getenv("ORCHESTRATOR_REQUEST_RATE_LIMIT", "120"))
RATE_WINDOW_SECONDS = int(os.getenv("ORCHESTRATOR_RATE_WINDOW_SECONDS", "60"))

_rate_buckets: dict[str, deque] = defaultdict(deque)
_rate_lock = Lock()


class Base(DeclarativeBase):
    pass


class TransactionRecord(Base):
    __tablename__ = "orchestrator_transactions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    correlation_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    from_office: Mapped[str | None] = mapped_column(String(64), nullable=True)
    to_office: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    to_manager: Mapped[str | None] = mapped_column(String(128), nullable=True)
    routed_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    routing_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    matched_keywords: Mapped[list] = mapped_column(JSON, default=list)
    action: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    instruction: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="pending", index=True)
    escalated: Mapped[bool] = mapped_column(Boolean, default=False)
    attempts: Mapped[list] = mapped_column(JSON, default=list)
    office_response: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class Worker(Base):
    __tablename__ = "workers"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    worker_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(128), index=True)
    email: Mapped[str | None] = mapped_column(String(128), nullable=True)
    floor: Mapped[str] = mapped_column(String(16), index=True)
    teams: Mapped[list] = mapped_column(JSON, default=list)
    assigned_platforms: Mapped[list] = mapped_column(JSON, default=list)
    status: Mapped[str] = mapped_column(String(32), default="active", index=True)
    role: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


engine = create_engine(DATABASE_URL, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
Base.metadata.create_all(bind=engine)

_log_event(
    logging.INFO,
    "orchestrator_initialized",
    database_url=_redact_database_url(DATABASE_URL),
    api_key_mode="configured",
)


def _serialize_transaction(record: TransactionRecord) -> dict:
    return {
        "id": record.id,
        "correlation_id": record.correlation_id,
        "from_office": record.from_office,
        "to_office": record.to_office,
        "to_manager": record.to_manager,
        "routed_reason": record.routed_reason,
        "routing_confidence": record.routing_confidence,
        "matched_keywords": record.matched_keywords or [],
        "action": record.action,
        "instruction": record.instruction,
        "status": record.status,
        "escalated": record.escalated,
        "attempts": record.attempts or [],
        "office_response": record.office_response,
        "error": record.error,
        "timestamp": record.created_at.isoformat() if record.created_at else None,
        "updated_at": record.updated_at.isoformat() if record.updated_at else None,
    }


def _append_transaction(tx: dict) -> dict:
    with SessionLocal() as session:
        row = TransactionRecord(
            correlation_id=tx.get("correlation_id"),
            from_office=tx.get("from_office"),
            to_office=tx.get("to_office"),
            to_manager=tx.get("to_manager"),
            routed_reason=tx.get("routed_reason"),
            routing_confidence=tx.get("routing_confidence"),
            matched_keywords=tx.get("matched_keywords", []),
            action=tx.get("action"),
            instruction=tx.get("instruction"),
            status=tx.get("status", "pending"),
            escalated=tx.get("escalated", False),
            attempts=tx.get("attempts", []),
            office_response=tx.get("office_response"),
            error=tx.get("error"),
        )
        session.add(row)
        session.commit()
        session.refresh(row)
        return _serialize_transaction(row)


def _update_transaction(transaction_id: int, updates: dict) -> dict | None:
    with SessionLocal() as session:
        row = session.get(TransactionRecord, transaction_id)
        if not row:
            return None
        for key, value in updates.items():
            if hasattr(row, key):
                setattr(row, key, value)
        session.commit()
        session.refresh(row)
        return _serialize_transaction(row)


def _get_transactions(limit: int = 100, action: str | None = None, office: str | None = None, status: str | None = None) -> list[dict]:
    with SessionLocal() as session:
        query = session.query(TransactionRecord)
        if action:
            query = query.filter(TransactionRecord.action == action)
        if office:
            query = query.filter(TransactionRecord.to_office == office)
        if status:
            query = query.filter(TransactionRecord.status == status)

        rows = query.order_by(desc(TransactionRecord.id)).limit(limit).all()
        rows.reverse()
        return [_serialize_transaction(row) for row in rows]


def _enforce_rate_limit(endpoint_name: str, identity: str, limit: int, window_seconds: int) -> None:
    now = datetime.utcnow()
    cutoff = now - timedelta(seconds=window_seconds)
    bucket_key = f"{endpoint_name}:{identity}"

    with _rate_lock:
        events = _rate_buckets[bucket_key]
        while events and events[0] < cutoff:
            events.popleft()
        if len(events) >= limit:
            _log_event(
                logging.WARNING,
                "rate_limit_exceeded",
                endpoint=endpoint_name,
                identity=identity,
                current_count=len(events),
                limit=limit,
            )
            raise HTTPException(
                status_code=429,
                detail=f"Rate limit exceeded for {endpoint_name}. Try again shortly.",
            )
        events.append(now)


def require_api_key(x_api_key: str | None = Header(default=None, alias="X-API-Key")) -> str:
    if not x_api_key or x_api_key != API_KEY:
        _log_event(logging.WARNING, "auth_failed", reason="invalid_or_missing_api_key")
        raise HTTPException(status_code=401, detail="Invalid or missing API key")
    return x_api_key


def _rate_limiter(endpoint_name: str, limit: int):
    def dependency(request: Request, api_key: str = Depends(require_api_key)) -> str:
        identity = api_key or request.client.host if request.client else "anonymous"
        _enforce_rate_limit(endpoint_name=endpoint_name, identity=identity, limit=limit, window_seconds=RATE_WINDOW_SECONDS)
        return api_key

    return dependency


def metadata_guard(request: Request, x_api_key: str | None = Header(default=None, alias="X-API-Key")) -> None:
    if not REQUIRE_METADATA_AUTH:
        return

    api_key = require_api_key(x_api_key)
    identity = api_key or (request.client.host if request.client else "anonymous")
    _enforce_rate_limit(
        endpoint_name="metadata",
        identity=identity,
        limit=DISPATCH_RATE_LIMIT,
        window_seconds=RATE_WINDOW_SECONDS,
    )


rate_limit_message = _rate_limiter("message", MESSAGE_RATE_LIMIT)
rate_limit_dispatch = _rate_limiter("dispatch-log", DISPATCH_RATE_LIMIT)
rate_limit_request = _rate_limiter("request", REQUEST_RATE_LIMIT)


def route_task_to_office(instruction: str) -> tuple[str, str, float, list]:
    """Route a task to the best office based on keyword matching."""
    text = instruction.lower()
    best_office = "customer-service"
    best_score = 0
    matched_keywords = []

    for office, keywords in ROUTING_KEYWORDS.items():
        local_matches = [keyword for keyword in keywords if keyword in text]
        score = len(local_matches)
        if score > best_score:
            best_score = score
            best_office = office
            matched_keywords = local_matches

    if best_score == 0:
        return best_office, "No strong keyword match; defaulted to Customer Service manager for triage.", 0.25, []

    max_possible = max(1, len(ROUTING_KEYWORDS.get(best_office, [])))
    confidence = min(0.95, round(0.35 + (best_score / max_possible), 2))
    return best_office, f"Matched task keywords to {best_office} office domain.", confidence, matched_keywords


def _normalize_platform(platform: str) -> str:
    value = (platform or "").strip().lower()
    if value == "twitter":
        return "x"
    return value


def _extract_requested_platforms(instruction: str, explicit_platforms: list[str] | None = None) -> list[str]:
    platforms = []

    for platform in explicit_platforms or []:
        normalized = _normalize_platform(platform)
        if normalized and normalized not in platforms:
            platforms.append(normalized)

    text = (instruction or "").lower()
    token_map = {
        "x": [r"\bx\b", r"twitter", r"tweet"],
        "instagram": [r"instagram", r"\big\b"],
        "linkedin": [r"linkedin"],
        "tiktok": [r"tiktok", r"tik\s+tok"],
        "facebook": [r"facebook", r"\bfb\b"],
    }
    for platform, patterns in token_map.items():
        if any(re.search(pattern, text) for pattern in patterns):
            if platform not in platforms:
                platforms.append(platform)

    return platforms


def _extract_sales_research_keywords(instruction: str, matched_keywords: list[str]) -> list[str]:
    text = (instruction or "").lower()
    stop_words = {
        "the", "and", "for", "with", "that", "this", "from", "into", "about", "please",
        "need", "show", "give", "make", "create", "build", "plan", "review", "analysis",
        "cost", "hr", "risk", "offensive", "gross", "sales", "team", "floor", "strategy",
    }

    tokens = re.findall(r"\b[a-z][a-z0-9_-]{2,}\b", text)
    ordered_keywords: list[str] = []

    for keyword in matched_keywords or []:
        normalized = keyword.strip().lower()
        if normalized and normalized not in ordered_keywords:
            ordered_keywords.append(normalized)

    for token in tokens:
        if token in stop_words:
            continue
        if token not in ordered_keywords:
            ordered_keywords.append(token)
        if len(ordered_keywords) >= 8:
            break

    if not ordered_keywords:
        return ["market trends", "sales opportunities"]
    return ordered_keywords[:8]


def _text_matches_any(text: str, keywords: list[str]) -> bool:
    return any(keyword in text for keyword in keywords)


def _build_ceo_review_council_roles(to_office: str, instruction: str) -> tuple[str, list[dict], bool] | None:
    if to_office not in CEO_REVIEW_COUNCIL_OFFICES:
        return None

    text = (instruction or "").lower()
    collaborator_offices = []
    for office, profile in CEO_REVIEW_COUNCIL_OFFICES.items():
        if office == to_office:
            continue
        if _text_matches_any(text, profile.get("keywords", [])):
            collaborator_offices.append(office)

    if not collaborator_offices:
        coordination_tokens = ["follow up", "follow-up", "delegate", "delegation", "next step", "next steps", "scope", "ceo review", "council"]
        if not _text_matches_any(text, coordination_tokens):
            return None
        collaborator_offices = list(CEO_REVIEW_DEFAULT_PEERS.get(to_office, []))

    roles = [
        {
            "name": "owner",
            "office": to_office,
            "manager": OFFICE_MANAGERS.get(to_office, "Office Manager Agent"),
            "requires_remote": True,
            "allow_fallback": False,
        }
    ]

    for office in collaborator_offices:
        roles.append(
            {
                "name": f"council-{office}-review",
                "office": office,
                "manager": OFFICE_MANAGERS.get(office, "Office Manager Agent"),
                "requires_remote": True,
                "allow_fallback": False,
            }
        )

    return "ceo-review-council", roles, False


def _build_council_scope_and_collaborators(
    *,
    to_office: str,
    collaborator_offices: list[str],
    office_profiles: dict[str, dict],
    partner_relationship: str,
    default_manager: str,
) -> tuple[list[str], list[dict]]:
    scope_tags = []
    collaborators = []
    for office in collaborator_offices:
        profile = office_profiles[office]
        label = profile.get("label", office)
        if label not in scope_tags:
            scope_tags.append(label)
        collaborators.append(
            {
                "office": office,
                "manager": OFFICE_MANAGERS.get(office, default_manager),
                "relationship": "owner" if office == to_office else partner_relationship,
                "bidirectional": True,
                "purpose": profile.get("purpose"),
                "follow_up": profile.get("follow_up"),
            }
        )
    return scope_tags, collaborators


def _build_council_payload_base(
    *,
    to_office: str,
    owner_manager_default: str,
    scope_tags: list[str],
    matched_keywords: list[str],
    collaborators: list[dict],
    delegation_rules: list[str],
    next_steps: list[str],
    extra_fields: dict | None = None,
) -> dict:
    payload = {
        "enabled": True,
        "bidirectional": True,
        "owner_office": to_office,
        "owner_manager": OFFICE_MANAGERS.get(to_office, owner_manager_default),
        "scope_tags": scope_tags,
        "matched_keywords": matched_keywords[:8],
        "collaborators": collaborators,
        "delegation_rules": delegation_rules,
        "next_steps": next_steps,
    }
    if extra_fields:
        payload.update(extra_fields)
    return payload


def _build_ceo_review_council_payload(
    to_office: str,
    instruction: str,
    matched_keywords: list[str],
    workflow_roles: list[dict],
) -> dict | None:
    if to_office not in CEO_REVIEW_COUNCIL_OFFICES:
        return None

    text = (instruction or "").lower()
    collaborator_offices = []
    for role in workflow_roles or []:
        office = role.get("office")
        if office in CEO_REVIEW_COUNCIL_OFFICES and office not in collaborator_offices:
            collaborator_offices.append(office)
    if to_office not in collaborator_offices:
        collaborator_offices.insert(0, to_office)

    scope_tags, collaborators = _build_council_scope_and_collaborators(
        to_office=to_office,
        collaborator_offices=collaborator_offices,
        office_profiles=CEO_REVIEW_COUNCIL_OFFICES,
        partner_relationship="review-partner",
        default_manager="Office Manager Agent",
    )

    fulfillment_targets = []
    for office, rule in FULFILLMENT_SCOPE_RULES.items():
        if _text_matches_any(text, rule.get("keywords", [])):
            fulfillment_targets.append(
                {
                    "office": office,
                    "manager": OFFICE_MANAGERS.get(office, "Office Manager Agent"),
                    "purpose": rule.get("purpose"),
                }
            )
    if fulfillment_targets and "fulfillment" not in scope_tags:
        scope_tags.append("fulfillment")

    next_steps = [
        f"{OFFICE_MANAGERS.get(to_office, 'Office Manager Agent')} owns the first response and keeps the council updated on blockers.",
        "Council reviewers return questions, constraints, and sign-off notes through the shared workflow context.",
    ]
    if fulfillment_targets:
        next_steps.append(
            "Delegate execution after council review to: "
            + ", ".join(target["office"] for target in fulfillment_targets)
            + "."
        )
    else:
        next_steps.append("Delegate execution outside Sector Beta through the orchestrator request path while preserving the same correlation id.")

    delegation_rules = [
        "Commercial changes, demand shifts, or launch timing questions delegate to Sales.",
        "Budget, spend, ROI, or funding decisions delegate to Finance.",
        "Policy, staffing, conduct, or hiring questions delegate to HR.",
        "Integration, security, platform, or systems readiness delegate to IT.",
    ]

    return _build_council_payload_base(
        to_office=to_office,
        owner_manager_default="Office Manager Agent",
        scope_tags=scope_tags,
        matched_keywords=matched_keywords,
        collaborators=collaborators,
        delegation_rules=delegation_rules,
        next_steps=next_steps,
        extra_fields={"fulfillment_targets": fulfillment_targets},
    )


def _build_gamma_council_payload(
    to_office: str,
    instruction: str,
    matched_keywords: list[str],
) -> dict | None:
    if to_office not in GAMMA_COUNCIL_OFFICES:
        return None

    text = (instruction or "").lower()
    
    # Find collaborators within Gamma based on content relevance
    collaborator_offices = [to_office]
    gamma_keywords_by_office = {
        office: GAMMA_COUNCIL_OFFICES[office].get("keywords", [])
        for office in GAMMA_COUNCIL_OFFICES
    }
    
    # Add peer offices that match the instruction keywords
    for office in GAMMA_COUNCIL_DEFAULT_PEERS.get(to_office, []):
        if office not in collaborator_offices and _text_matches_any(text, gamma_keywords_by_office.get(office, [])):
            collaborator_offices.append(office)

    scope_tags, collaborators = _build_council_scope_and_collaborators(
        to_office=to_office,
        collaborator_offices=collaborator_offices,
        office_profiles=GAMMA_COUNCIL_OFFICES,
        partner_relationship="coordination-partner",
        default_manager="Operations Agent",
    )

    # Determine if escalation to Beta council is needed
    escalation_triggers = ["commercial", "budget", "policy", "security", "integration"]
    should_escalate_to_beta = _text_matches_any(text, escalation_triggers)
    
    beta_escalation_targets = []
    if should_escalate_to_beta:
        # Map Gamma to Beta for escalation
        gamma_to_beta_map = {
            "procurement": "finance",
            "manufacturing": "finance",
            "customer-service": "sales",
            "social-media": "sales",
        }
        escalation_office = gamma_to_beta_map.get(to_office, "finance")
        if escalation_office in CEO_REVIEW_COUNCIL_OFFICES:
            profile = CEO_REVIEW_COUNCIL_OFFICES[escalation_office]
            beta_escalation_targets.append(
                {
                    "office": escalation_office,
                    "manager": OFFICE_MANAGERS.get(escalation_office, "Office Manager Agent"),
                    "purpose": profile.get("purpose"),
                    "reason": f"Cross-functional concern from {to_office}",
                }
            )

    next_steps = [
        f"{OFFICE_MANAGERS.get(to_office, 'Operations Agent')} owns the first fulfillment action and coordinates with Gamma council partners.",
        "Gamma council partners return fulfillment constraints, escalation flags, and status updates through shared workflow context.",
    ]
    
    if should_escalate_to_beta and beta_escalation_targets:
        next_steps.append(
            f"Escalate cross-functional concerns to {', '.join(t['office'] for t in beta_escalation_targets)} via Sector Beta CEO Review Council if blockers exceed Gamma scope."
        )

    delegation_rules = [
        "Sourcing, vendor, and supply chain questions delegate to Procurement.",
        "Production capacity, quality, and throughput questions delegate to Manufacturing.",
        "Customer impact, feedback, and support questions delegate to Customer Service.",
        "Messaging, content, and campaign questions delegate to Social Media.",
        "Budget and ROI concerns escalate to Sector Beta Finance.",
        "Commercial timing and market concerns escalate to Sector Beta Sales.",
    ]

    return _build_council_payload_base(
        to_office=to_office,
        owner_manager_default="Operations Agent",
        scope_tags=scope_tags,
        matched_keywords=matched_keywords,
        collaborators=collaborators,
        delegation_rules=delegation_rules,
        next_steps=next_steps,
        extra_fields={
            "escalation_targets": beta_escalation_targets,
            "should_escalate_to_beta": should_escalate_to_beta,
        },
    )


def _should_auto_sales_research_review(
    *,
    from_office: str,
    to_office: str,
    is_auto_route: bool,
    instruction: str,
) -> bool:
    if to_office != "sales":
        return False
    if from_office not in {"user", "me"}:
        return False
    if not is_auto_route:
        return False
    return len((instruction or "").strip()) >= 8


async def _run_sales_research_review_automation(
    *,
    client: httpx.AsyncClient,
    instruction: str,
    matched_keywords: list[str],
    requested_by: str,
) -> dict:
    keywords = _extract_sales_research_keywords(instruction, matched_keywords)

    trend_report = None
    trend_error = None
    try:
        trend_response = await client.post(
            f"{OFFICES['sales']}/trends/run",
            json={"keywords": keywords, "top_n": 5},
            timeout=60.0,
        )
        if trend_response.status_code == 200:
            trend_payload = trend_response.json()
            trend_report = trend_payload.get("report")
        else:
            trend_error = f"Trend dispatch returned {trend_response.status_code}"
    except Exception as exc:
        trend_error = str(exc)

    review_error = None
    review_packet = None
    try:
        review_response = await client.post(
            f"{OFFICES['sales']}/research/review",
            json={
                "request_text": instruction,
                "keywords": keywords,
                "trend_report": trend_report,
                "requested_by": requested_by,
            },
            timeout=30.0,
        )
        if review_response.status_code == 200:
            review_payload = review_response.json()
            review_packet = review_payload.get("review_packet")
        else:
            review_error = f"Weighted review returned {review_response.status_code}"
    except Exception as exc:
        review_error = str(exc)

    if review_packet:
        return {
            "status": "success",
            "keywords": keywords,
            "trend_dispatch": {
                "status": "success" if trend_report else "degraded",
                "error": trend_error,
                "raw_signal_count": (trend_report or {}).get("raw_signal_count", 0),
            },
            "review_packet": review_packet,
        }

    return {
        "status": "error",
        "keywords": keywords,
        "trend_dispatch": {
            "status": "success" if trend_report else "error",
            "error": trend_error,
            "raw_signal_count": (trend_report or {}).get("raw_signal_count", 0),
        },
        "error": review_error or "Automated research review did not return a packet.",
    }


def _find_workflow_stage_payload(workflow_summary: list[dict], role_name: str) -> dict:
    for stage in workflow_summary or []:
        if stage.get("role") != role_name:
            continue
        return ((stage.get("stage_response") or {}).get("data") or {})
    return {}


async def _publish_approved_social_campaign(instruction: str, workflow_summary: list[dict]) -> dict:
    creator_payload = _find_workflow_stage_payload(workflow_summary, "creator")
    integration_payload = _find_workflow_stage_payload(workflow_summary, "integration-reviewer")

    generated_posts = creator_payload.get("generated_posts") or []
    artifact_folder = creator_payload.get("artifact_folder", "")
    platforms = integration_payload.get("ready_platforms") or creator_payload.get("recommended_platforms") or _extract_requested_platforms(instruction)

    if not generated_posts:
        return {
            "status": "error",
            "message": "Approved social workflow did not produce any posts to publish.",
        }

    async with httpx.AsyncClient() as client:
        response = await client.post(
            f"{OFFICES['it']}/publish",
            json={
                "posts": generated_posts,
                "platforms": platforms or [],
                "artifact_folder": artifact_folder,
            },
            timeout=60.0,
        )

    if response.status_code != 200:
        return {
            "status": "error",
            "message": f"IT publish failed with status {response.status_code}",
        }

    return response.json()


def _resolve_workflow_policy(to_office: str, instruction: str) -> tuple[str | None, dict | None]:
    text = (instruction or "").lower()
    office_policies = [
        (policy_id, policy)
        for policy_id, policy in WORKFLOW_POLICIES.items()
        if policy.get("office") == to_office
    ]

    for policy_id, policy in office_policies:
        trigger_keywords = policy.get("trigger_keywords") or []
        if trigger_keywords and any(keyword in text for keyword in trigger_keywords):
            return policy_id, policy

    for policy_id, policy in office_policies:
        trigger_keywords = policy.get("trigger_keywords") or []
        if not trigger_keywords:
            return policy_id, policy

    return None, None


def _build_workflow_roles(to_office: str, instruction: str) -> tuple[str | None, list[dict], bool]:
    policy_id, policy = _resolve_workflow_policy(to_office, instruction)
    if not policy:
        council_roles = _build_ceo_review_council_roles(to_office, instruction)
        if council_roles:
            return council_roles
        return None, [
            {
                "name": "owner",
                "office": to_office,
                "manager": OFFICE_MANAGERS.get(to_office, "Office Manager Agent"),
                "requires_remote": True,
                "allow_fallback": True,
            }
        ], False
    return policy_id, [dict(role) for role in policy["roles"]], bool(policy.get("requires_final_user_approval", False))


def _coordinator_quality_gate(instruction: str, prior_attempts: list[dict]) -> tuple[bool, str]:
    text = (instruction or "").strip()
    if len(text) < 20:
        return False, "Instruction is too brief for executive approval. Add campaign goal, audience, and channel guidance."

    if not any(attempt.get("role") == "reviewer" and attempt.get("status_code") == 200 for attempt in prior_attempts):
        return False, "HR review did not complete successfully, so coordinator approval is blocked."

    return True, "Coordinator approval granted after successful creator and reviewer stages."


def _validate_workflow_request(instruction: str, workflow_roles: list[dict]) -> None:
    text = (instruction or "").strip()
    if len(text) < 8:
        raise HTTPException(status_code=400, detail="Instruction must be at least 8 characters for workflow dispatch")

    role_names = [role.get("name") for role in workflow_roles]
    if "approver" in role_names and "reviewer" not in role_names:
        raise HTTPException(status_code=500, detail="Workflow policy misconfiguration: approver requires reviewer stage")


def _validate_workflow_completion(workflow_roles: list[dict], attempts: list[dict]) -> tuple[bool, str]:
    successful = {
        attempt.get("role")
        for attempt in attempts
        if attempt.get("status_code") == 200 and attempt.get("role")
    }

    required_roles = [role.get("name") for role in workflow_roles]
    missing = [role_name for role_name in required_roles if role_name not in successful]
    if missing:
        return False, f"Workflow completion blocked: missing successful stages: {', '.join(missing)}"

    ordered_successes = [attempt.get("role") for attempt in attempts if attempt.get("status_code") == 200]
    expected_order = [role.get("name") for role in workflow_roles]
    pointer = 0
    for role_name in ordered_successes:
        if pointer < len(expected_order) and role_name == expected_order[pointer]:
            pointer += 1
    if pointer != len(expected_order):
        return False, "Workflow completion blocked: required role sequence was not observed"

    return True, "Workflow integrity checks passed"


def _build_final_approval_payload(policy_id: str | None, queue_state: str, action_hint: str) -> dict:
    return {
        "required": True,
        "queue_state": queue_state,
        "policy": policy_id,
        "action_hint": action_hint,
    }


def _get_transaction_by_id(transaction_id: int) -> dict | None:
    with SessionLocal() as session:
        row = session.get(TransactionRecord, transaction_id)
        if not row:
            return None
        return _serialize_transaction(row)


@app.get("/health")
async def health_check():
    """Health check endpoint"""
    return {
        "status": "healthy",
        "service": "office-orchestrator",
        "timestamp": datetime.utcnow().isoformat(),
    }


@app.get("/offices")
async def list_offices(_guard: None = Depends(metadata_guard)):
    """Get all office statuses"""
    statuses = {}

    async with httpx.AsyncClient() as client:
        for office_name, office_url in OFFICES.items():
            try:
                response = await client.get(f"{office_url}/health", timeout=5.0)
                statuses[office_name] = {
                    "status": "online" if response.status_code == 200 else "error",
                    "url": office_url,
                }
            except Exception as e:
                statuses[office_name] = {
                    "status": "offline",
                    "url": office_url,
                    "error": str(e),
                }

    return {"offices": statuses}


@app.get("/integrations/status")
async def get_integration_status(_guard: None = Depends(metadata_guard)):
    """Return merged IT integration catalog with current linked status."""
    async with httpx.AsyncClient() as client:
        try:
            catalog_response = await client.get(f"{OFFICES['it']}/integrations/catalog", timeout=10.0)
            links_response = await client.get(f"{OFFICES['it']}/integrations", timeout=10.0)
        except Exception as e:
            raise HTTPException(status_code=502, detail=f"Failed to reach IT office: {str(e)}")

    if catalog_response.status_code != 200:
        raise HTTPException(status_code=502, detail="Failed to load IT integration catalog")
    if links_response.status_code != 200:
        raise HTTPException(status_code=502, detail="Failed to load IT integration links")

    catalog_payload = catalog_response.json() if catalog_response.headers.get("content-type", "").startswith("application/json") else {}
    links_payload = links_response.json() if links_response.headers.get("content-type", "").startswith("application/json") else {}

    catalog = catalog_payload.get("catalog") or {}
    linked = links_payload.get("integrations") or {}

    connections = []
    for integration_id in sorted(catalog.keys()):
        definition = catalog.get(integration_id) or {}
        linked_record = linked.get(integration_id) or {}
        connected = integration_id in linked
        connections.append(
            {
                "id": integration_id,
                "name": definition.get("name", integration_id.title()),
                "category": definition.get("category", "unknown"),
                "publish_capable": bool(definition.get("publish_capable")),
                "custom": bool(definition.get("custom")),
                "aliases": definition.get("aliases") or [],
                "connected": connected,
                "account_name": linked_record.get("account_name"),
                "credential_ref": linked_record.get("credential_ref"),
                "linked_at": linked_record.get("linked_at"),
                "status": linked_record.get("status", "linked" if connected else "not-linked"),
                "secure_connection": bool(linked_record.get("secure_connection")),
                "connection_method": linked_record.get("connection_method"),
                "security_level": linked_record.get("security_level"),
                "scopes": linked_record.get("scopes") or [],
                "verified_at": linked_record.get("verified_at"),
                "last_security_check": linked_record.get("last_security_check"),
                "required_scopes": definition.get("required_scopes") or [],
            }
        )

    return {
        "status": "success",
        "connections": connections,
        "linked_count": len(linked),
        "catalog_count": len(catalog),
        "default_publish_targets": links_payload.get("default_publish_targets") or [],
    }


@app.post("/integrations/catalog/add")
async def add_integration_catalog_item(request: IntegrationCatalogCreateRequest, _auth: str = Depends(rate_limit_dispatch)):
    payload = request.model_dump()
    async with httpx.AsyncClient() as client:
        response = await client.post(f"{OFFICES['it']}/integrations/catalog/add", json=payload, timeout=20.0)
    if response.status_code != 200:
        raise HTTPException(status_code=502, detail="Failed to add integration through IT office")
    return response.json()


@app.post("/integrations/link")
async def link_integration_proxy(request: IntegrationLinkRequest, _auth: str = Depends(rate_limit_dispatch)):
    payload = request.model_dump(exclude_none=True)
    async with httpx.AsyncClient() as client:
        response = await client.post(f"{OFFICES['it']}/integrations/link-secure", json=payload, timeout=20.0)
    if response.status_code != 200:
        raise HTTPException(status_code=502, detail="Failed to link integration through IT office")
    return response.json()


@app.post("/integrations/unlink")
async def unlink_integration_proxy(request: IntegrationLinkRequest, _auth: str = Depends(rate_limit_dispatch)):
    payload = {"integration": request.integration}
    async with httpx.AsyncClient() as client:
        response = await client.post(f"{OFFICES['it']}/integrations/unlink", json=payload, timeout=20.0)
    if response.status_code != 200:
        raise HTTPException(status_code=502, detail="Failed to unlink integration through IT office")
    return response.json()


@app.post("/request")
async def submit_request(request_data: dict, _auth: str = Depends(rate_limit_request)):
    """Submit a cross-office request"""
    from_office = request_data.get("from_office")
    to_office = request_data.get("to_office")

    if to_office not in OFFICES:
        logger.error(f"Invalid office: {to_office}")
        raise HTTPException(status_code=400, detail=f"Office '{to_office}' not found")

    transaction = _append_transaction(
        {
            "from_office": from_office,
            "to_office": to_office,
            "action": request_data.get("action"),
            "status": "pending",
        }
    )

    logger.info(f"Request {transaction['id']}: {from_office} ? {to_office} ({request_data.get('action')})")

    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{OFFICES[to_office]}/handle-request",
                json=request_data,
                timeout=30.0,
            )

            updated = _update_transaction(
                transaction["id"],
                {
                    "status": "completed" if response.status_code == 200 else "failed",
                    "office_response": response.json() if response.status_code == 200 else None,
                },
            )

            logger.info(f"Request {transaction['id']} completed with status {updated['status'] if updated else 'unknown'}")

            return {
                "request_id": transaction["id"],
                "status": updated["status"] if updated else "failed",
                "response": response.json() if response.status_code == 200 else None,
            }
    except Exception as e:
        logger.error(f"Request {transaction['id']} failed: {str(e)}")
        _update_transaction(transaction["id"], {"status": "error", "error": str(e)})
        raise HTTPException(status_code=500, detail=f"Failed to route request: {str(e)}")


@app.post("/message", response_model=MessageResponse)
async def message_office(payload: MessageRequest, _auth: str = Depends(rate_limit_message)):
    """C-suite executive controller routes natural-language tasks to office managers."""
    if isinstance(payload, dict):
        to_office = payload.get("to_office")
        instruction = (payload.get("instruction") or "").strip()
        from_office = payload.get("from_office", "user")
        data = payload.get("data", {})
    else:
        to_office = payload.to_office
        instruction = payload.instruction.strip()
        from_office = payload.from_office
        data = payload.data

    data = dict(data or {})
    requested_platforms = _extract_requested_platforms(instruction, data.get("platforms") or [])
    if requested_platforms and not data.get("platforms"):
        data["platforms"] = requested_platforms

    is_auto_route = not to_office or to_office == "auto"
    routed_reason = "Explicit office target requested."
    routed_confidence = 1.0
    matched_keywords = []
    if is_auto_route:
        to_office, routed_reason, routed_confidence, matched_keywords = route_task_to_office(instruction)

    if to_office not in OFFICES:
        logger.error(f"Invalid office for routing: {to_office}")
        raise HTTPException(status_code=400, detail=f"Office '{to_office}' not found")

    if to_office == "social-media" and not data.get("publish_target_mode"):
        data["publish_target_mode"] = "all-linked-social"

    target_manager = OFFICE_MANAGERS.get(to_office, "Office Manager Agent")
    workflow_policy_id, workflow_roles, requires_final_user_approval = _build_workflow_roles(to_office, instruction)
    council_payload = _build_ceo_review_council_payload(to_office, instruction, matched_keywords, workflow_roles)
    gamma_council_payload = _build_gamma_council_payload(to_office, instruction, matched_keywords)
    _validate_workflow_request(instruction, workflow_roles)

    transaction = _append_transaction(
        {
            "correlation_id": str(uuid.uuid4()),
            "from_office": from_office,
            "to_office": to_office,
            "to_manager": target_manager,
            "routed_reason": routed_reason,
            "routing_confidence": routed_confidence,
            "matched_keywords": matched_keywords,
            "action": "message",
            "instruction": instruction,
            "status": "pending",
            "attempts": [],
        }
    )

    _log_event(
        logging.INFO,
        "dispatch_routed",
        correlation_id=transaction["correlation_id"],
        to_office=to_office,
        routing_confidence=routed_confidence,
    )

    if council_payload:
        council_payload["correlation_id"] = transaction["correlation_id"]
        data["ceo_review_council"] = council_payload

    if gamma_council_payload:
        gamma_council_payload["correlation_id"] = transaction["correlation_id"]
        data["ceo_operations_council"] = gamma_council_payload

    base_request_data = {
        "from_office": from_office,
        "routed_reason": routed_reason,
        "routing_confidence": routed_confidence,
        "matched_keywords": matched_keywords,
        "action": "message",
        "instruction": instruction,
        "data": data,
    }

    try:
        async with httpx.AsyncClient() as client:
            last_error = None
            primary_role_name = workflow_roles[0].get("name", "owner") if workflow_roles else "owner"
            owner_delivery_office = to_office
            owner_delivery_manager = target_manager
            auto_sales_review = None

            workflow_summary = []

            for stage_index, role in enumerate(workflow_roles, start=1):
                role_name = role.get("name", "owner")
                role_office = role.get("office", to_office)
                role_manager = role.get("manager", OFFICE_MANAGERS.get(role_office, "Office Manager Agent"))
                requires_remote = bool(role.get("requires_remote", True))
                allow_fallback = bool(role.get("allow_fallback", True))

                if not requires_remote:
                    approved, approval_reason = _coordinator_quality_gate(
                        instruction=instruction,
                        prior_attempts=transaction.get("attempts", []),
                    )
                    current_attempts = list(transaction.get("attempts") or [])
                    current_attempts.append(
                        {
                            "role": role_name,
                            "office": role_office,
                            "manager": role_manager,
                            "status_code": 200 if approved else 422,
                            "approval_reason": approval_reason,
                            "timestamp": datetime.utcnow().isoformat(),
                        }
                    )
                    transaction["attempts"] = current_attempts
                    workflow_summary.append(
                        {
                            "role": role_name,
                            "office": role_office,
                            "manager": role_manager,
                            "status": "completed" if approved else "failed",
                            "reason": approval_reason,
                        }
                    )

                    if not approved:
                        _update_transaction(
                            transaction["id"],
                            {
                                "status": "failed",
                                "attempts": current_attempts,
                                "error": approval_reason,
                                "office_response": {"workflow": workflow_summary},
                            },
                        )
                        _log_event(
                            logging.WARNING,
                            "dispatch_completed",
                            correlation_id=transaction["correlation_id"],
                            to_office=to_office,
                            status_code=422,
                            final_status="failed",
                            escalated=False,
                        )
                        return MessageResponse(
                            request_id=transaction["id"],
                            correlation_id=transaction["correlation_id"],
                            status="failed",
                            executive_controller="Office Orchestrator (C-suite)",
                            to_office=to_office,
                            to_manager=target_manager,
                            routed_reason=routed_reason,
                            routing_confidence=routed_confidence,
                            matched_keywords=matched_keywords,
                            escalated=False,
                            instruction=instruction,
                            response={"workflow": workflow_summary, "approval_reason": approval_reason},
                            attempts=current_attempts,
                        ).model_dump()

                    _update_transaction(
                        transaction["id"],
                        {
                            "attempts": current_attempts,
                            "office_response": {"workflow": workflow_summary},
                        },
                    )
                    continue

                primary_office = role_office
                fallback_office = FALLBACK_OFFICE.get(primary_office, "customer-service")
                if allow_fallback and fallback_office != primary_office:
                    stage_targets = [primary_office, fallback_office]
                else:
                    stage_targets = [primary_office]
                stage_succeeded = False

                for attempt_office in stage_targets:
                    attempt_manager = OFFICE_MANAGERS.get(attempt_office, "Office Manager Agent")
                    stage_data = dict(base_request_data.get("data") or {})
                    stage_data["workflow_context"] = {"workflow": workflow_summary}
                    request_data = {
                        **base_request_data,
                        "to_office": attempt_office,
                        "to_manager": attempt_manager,
                        "workflow_role": role_name,
                        "workflow_stage": stage_index,
                        "workflow_total_stages": len(workflow_roles),
                        "correlation_id": transaction["correlation_id"],
                        "workflow_context": {"workflow": workflow_summary},
                        "data": stage_data,
                    }

                    current_attempts = list(transaction.get("attempts") or [])

                    try:
                        response = await client.post(
                            f"{OFFICES[attempt_office]}/handle-request",
                            json=request_data,
                            timeout=60.0,
                        )
                        response_body = (
                            response.json()
                            if response.headers.get("content-type", "").startswith("application/json")
                            else {"raw": response.text}
                        )
                        current_attempts.append(
                            {
                                "role": role_name,
                                "office": attempt_office,
                                "manager": attempt_manager,
                                "status_code": response.status_code,
                                "stage": stage_index,
                                "timestamp": datetime.utcnow().isoformat(),
                            }
                        )
                        transaction["attempts"] = current_attempts

                        if response.status_code == 200:
                            stage_succeeded = True
                            if stage_index == 1:
                                owner_delivery_office = attempt_office
                                owner_delivery_manager = attempt_manager
                            workflow_summary.append(
                                {
                                    "role": role_name,
                                    "office": attempt_office,
                                    "manager": attempt_manager,
                                    "status": "completed",
                                    "stage_response": response_body,
                                }
                            )
                            _update_transaction(transaction["id"], {"attempts": current_attempts})
                            break

                        if response.status_code < 500:
                            error_message = f"Workflow stage '{role_name}' rejected by {attempt_office} with status {response.status_code}"
                            _update_transaction(
                                transaction["id"],
                                {
                                    "status": "failed",
                                    "attempts": current_attempts,
                                    "error": error_message,
                                    "office_response": {
                                        "workflow": workflow_summary,
                                        "stage_response": response_body,
                                    },
                                },
                            )
                            _log_event(
                                logging.WARNING,
                                "dispatch_completed",
                                correlation_id=transaction["correlation_id"],
                                to_office=attempt_office,
                                status_code=response.status_code,
                                final_status="failed",
                                escalated=attempt_office != primary_office,
                            )
                            return MessageResponse(
                                request_id=transaction["id"],
                                correlation_id=transaction["correlation_id"],
                                status="failed",
                                executive_controller="Office Orchestrator (C-suite)",
                                to_office=to_office,
                                to_manager=target_manager,
                                routed_reason=routed_reason,
                                routing_confidence=routed_confidence,
                                matched_keywords=matched_keywords,
                                escalated=attempt_office != primary_office,
                                instruction=instruction,
                                response={
                                    "workflow": workflow_summary,
                                    "stage_response": response_body,
                                    "error": error_message,
                                },
                                attempts=current_attempts,
                            ).model_dump()

                        last_error = f"Office {attempt_office} returned {response.status_code}"
                    except Exception as e:
                        _log_event(
                            logging.ERROR,
                            "dispatch_attempt_failed",
                            correlation_id=transaction["correlation_id"],
                            to_office=attempt_office,
                            error=str(e),
                        )
                        current_attempts.append(
                            {
                                "role": role_name,
                                "office": attempt_office,
                                "manager": attempt_manager,
                                "error": str(e),
                                "stage": stage_index,
                                "timestamp": datetime.utcnow().isoformat(),
                            }
                        )
                        transaction["attempts"] = current_attempts
                        last_error = str(e)

                    _update_transaction(transaction["id"], {"attempts": transaction["attempts"]})

                if not stage_succeeded:
                    error_message = last_error or f"Workflow stage '{role_name}' failed"
                    _update_transaction(
                        transaction["id"],
                        {
                            "status": "error",
                            "error": error_message,
                            "escalated": True,
                            "attempts": transaction.get("attempts", []),
                            "office_response": {"workflow": workflow_summary},
                        },
                    )
                    _log_event(
                        logging.ERROR,
                        "dispatch_failed",
                        correlation_id=transaction["correlation_id"],
                        error=error_message,
                    )
                    raise HTTPException(status_code=500, detail=f"Failed to message office: {error_message}")

            workflow_ok, workflow_reason = _validate_workflow_completion(workflow_roles, transaction.get("attempts", []))
            if not workflow_ok:
                updated_failed = _update_transaction(
                    transaction["id"],
                    {
                        "status": "failed",
                        "error": workflow_reason,
                        "attempts": transaction.get("attempts", []),
                        "office_response": {"workflow": workflow_summary},
                    },
                )
                _log_event(
                    logging.WARNING,
                    "dispatch_completed",
                    correlation_id=transaction["correlation_id"],
                    to_office=to_office,
                    status_code=422,
                    final_status="failed",
                    escalated=False,
                )
                return MessageResponse(
                    request_id=transaction["id"],
                    correlation_id=transaction["correlation_id"],
                    status="failed",
                    executive_controller="Office Orchestrator (C-suite)",
                    to_office=to_office,
                    to_manager=target_manager,
                    routed_reason=routed_reason,
                    routing_confidence=routed_confidence,
                    matched_keywords=matched_keywords,
                    escalated=False,
                    instruction=instruction,
                    response={"workflow": workflow_summary, "error": workflow_reason},
                    attempts=updated_failed["attempts"] if updated_failed else transaction.get("attempts", []),
                ).model_dump()

            if _should_auto_sales_research_review(
                from_office=from_office,
                to_office=to_office,
                is_auto_route=is_auto_route,
                instruction=instruction,
            ):
                auto_sales_review = await _run_sales_research_review_automation(
                    client=client,
                    instruction=instruction,
                    matched_keywords=matched_keywords,
                    requested_by=from_office,
                )
                workflow_summary.append(
                    {
                        "role": "research-review-automation",
                        "office": "sales",
                        "manager": "Leia Organa",
                        "status": "completed" if auto_sales_review.get("status") == "success" else "degraded",
                        "stage_response": auto_sales_review,
                    }
                )

            response_payload = {"workflow": workflow_summary}
            if council_payload:
                response_payload["ceo_review_council"] = council_payload
            if gamma_council_payload:
                response_payload["ceo_operations_council"] = gamma_council_payload
            if auto_sales_review:
                response_payload["auto_research_review"] = auto_sales_review

            if requires_final_user_approval:
                final_approval = _build_final_approval_payload(
                    policy_id=workflow_policy_id,
                    queue_state="pending",
                    action_hint="Needs final user approval before execution is finalized.",
                )
                updated_queued = _update_transaction(
                    transaction["id"],
                    {
                        "status": "needs_final_approval",
                        "to_office": to_office,
                        "to_manager": target_manager,
                        "attempts": transaction.get("attempts", []),
                        "office_response": {
                            "workflow": workflow_summary,
                            "final_approval": final_approval,
                            "ceo_review_council": council_payload,
                            "ceo_operations_council": gamma_council_payload,
                            "auto_research_review": auto_sales_review,
                        },
                    },
                )
                _log_event(
                    logging.INFO,
                    "dispatch_pending_final_approval",
                    correlation_id=transaction["correlation_id"],
                    to_office=to_office,
                    policy=workflow_policy_id,
                )
                return MessageResponse(
                    request_id=transaction["id"],
                    correlation_id=transaction["correlation_id"],
                    status="needs_final_approval",
                    executive_controller="Office Orchestrator (C-suite)",
                    to_office=to_office,
                    to_manager=target_manager,
                    routed_reason=routed_reason,
                    routing_confidence=routed_confidence,
                    matched_keywords=matched_keywords,
                    escalated=any(
                        attempt.get("role") == primary_role_name and attempt.get("office") != to_office
                        for attempt in transaction.get("attempts", [])
                    ),
                    instruction=instruction,
                    response={**response_payload, "final_approval": final_approval},
                    attempts=updated_queued["attempts"] if updated_queued else transaction.get("attempts", []),
                ).model_dump()

            updated = _update_transaction(
                transaction["id"],
                {
                    "status": "completed",
                    "to_office": owner_delivery_office if len(workflow_roles) == 1 else to_office,
                    "to_manager": owner_delivery_manager if len(workflow_roles) == 1 else target_manager,
                    "escalated": any(
                        attempt.get("role") == primary_role_name and attempt.get("office") != to_office
                        for attempt in transaction.get("attempts", [])
                    ),
                    "attempts": transaction.get("attempts", []),
                    "office_response": response_payload,
                },
            )

            _log_event(
                logging.INFO,
                "dispatch_completed",
                correlation_id=transaction["correlation_id"],
                to_office=owner_delivery_office if len(workflow_roles) == 1 else to_office,
                status_code=200,
                final_status="completed",
                escalated=any(
                    attempt.get("role") == primary_role_name and attempt.get("office") != to_office
                    for attempt in transaction.get("attempts", [])
                ),
            )

            return MessageResponse(
                request_id=transaction["id"],
                correlation_id=transaction["correlation_id"],
                status="completed",
                executive_controller="Office Orchestrator (C-suite)",
                to_office=owner_delivery_office if len(workflow_roles) == 1 else to_office,
                to_manager=owner_delivery_manager if len(workflow_roles) == 1 else target_manager,
                routed_reason=routed_reason,
                routing_confidence=routed_confidence,
                matched_keywords=matched_keywords,
                escalated=any(
                    attempt.get("role") == primary_role_name and attempt.get("office") != to_office
                    for attempt in transaction.get("attempts", [])
                ),
                instruction=instruction,
                response=response_payload,
                attempts=updated["attempts"] if updated else transaction.get("attempts", []),
            ).model_dump()
    except HTTPException:
        raise
    except Exception as e:
        _log_event(
            logging.ERROR,
            "dispatch_exception",
            correlation_id=transaction.get("correlation_id"),
            error=str(e),
        )
        _update_transaction(transaction["id"], {"status": "error", "error": str(e)})
        raise HTTPException(status_code=500, detail=f"Failed to message office: {str(e)}")


@app.get("/dispatch-log")
async def get_dispatch_log(
    limit: int = 20,
    office: str | None = None,
    status: str | None = None,
    _auth: str = Depends(rate_limit_dispatch),
):
    """Get executive dispatch records with simple filters for monitoring."""
    if limit < 1:
        raise HTTPException(status_code=400, detail="limit must be >= 1")

    logs = _get_transactions(limit=limit, action="message", office=office, status=status)
    logger.info(f"Dispatch-log query: office={office}, status={status}, limit={limit}, results={len(logs)}")
    return {"logs": logs}


@app.get("/stats")
async def get_stats(_auth: str = Depends(rate_limit_dispatch)):
    """Get orchestrator operational statistics."""
    with SessionLocal() as session:
        total_transactions = session.query(TransactionRecord).count()
        message_transactions = session.query(TransactionRecord).filter(TransactionRecord.action == "message").count()
        completed = session.query(TransactionRecord).filter(TransactionRecord.status == "completed").count()
        failed = session.query(TransactionRecord).filter(TransactionRecord.status == "failed").count()
        error = session.query(TransactionRecord).filter(TransactionRecord.status == "error").count()
        escalated = session.query(TransactionRecord).filter(TransactionRecord.escalated == True).count()

    office_counts = {}
    for office_id in OFFICES.keys():
        with SessionLocal() as session:
            office_counts[office_id] = session.query(TransactionRecord).filter(
                TransactionRecord.to_office == office_id
            ).count()

    logger.info(f"Stats request: total={total_transactions}, completed={completed}, failed={failed}, error={error}")

    return {
        "total_transactions": total_transactions,
        "message_transactions": message_transactions,
        "by_status": {
            "completed": completed,
            "failed": failed,
            "error": error,
            "pending": total_transactions - completed - failed - error,
        },
        "escalated_count": escalated,
        "by_office": office_counts,
        "rate_limits": {
            "message": MESSAGE_RATE_LIMIT,
            "dispatch": DISPATCH_RATE_LIMIT,
            "request": REQUEST_RATE_LIMIT,
            "window_seconds": RATE_WINDOW_SECONDS,
        },
    }


@app.get("/metrics", response_class=PlainTextResponse)
async def get_metrics(_auth: str = Depends(rate_limit_dispatch)):
    """Expose lightweight Prometheus-style metrics for operational monitoring."""
    with SessionLocal() as session:
        total_transactions = session.query(TransactionRecord).count()
        message_transactions = session.query(TransactionRecord).filter(TransactionRecord.action == "message").count()
        completed = session.query(TransactionRecord).filter(TransactionRecord.status == "completed").count()
        failed = session.query(TransactionRecord).filter(TransactionRecord.status == "failed").count()
        error = session.query(TransactionRecord).filter(TransactionRecord.status == "error").count()
        escalated = session.query(TransactionRecord).filter(TransactionRecord.escalated == True).count()

        office_counts = {}
        for office_id in OFFICES.keys():
            office_counts[office_id] = session.query(TransactionRecord).filter(
                TransactionRecord.to_office == office_id
            ).count()

    with _rate_lock:
        bucket_counts = {
            "message": 0,
            "dispatch-log": 0,
            "request": 0,
        }
        for bucket_key, events in _rate_buckets.items():
            endpoint_name = bucket_key.split(":", 1)[0]
            if endpoint_name in bucket_counts:
                bucket_counts[endpoint_name] += len(events)

    lines = [
        "# HELP agentic_office_transactions_total Total number of orchestrator transactions.",
        "# TYPE agentic_office_transactions_total counter",
        f"agentic_office_transactions_total {total_transactions}",
        "# HELP agentic_office_message_transactions_total Total number of message transactions.",
        "# TYPE agentic_office_message_transactions_total counter",
        f"agentic_office_message_transactions_total {message_transactions}",
        "# HELP agentic_office_transactions_by_status Number of transactions by status.",
        "# TYPE agentic_office_transactions_by_status gauge",
        f'agentic_office_transactions_by_status{{status="completed"}} {completed}',
        f'agentic_office_transactions_by_status{{status="failed"}} {failed}',
        f'agentic_office_transactions_by_status{{status="error"}} {error}',
        f'agentic_office_transactions_by_status{{status="pending"}} {max(total_transactions - completed - failed - error, 0)}',
        "# HELP agentic_office_escalated_total Total number of escalated transactions.",
        "# TYPE agentic_office_escalated_total counter",
        f"agentic_office_escalated_total {escalated}",
        "# HELP agentic_office_transactions_by_office Number of transactions by destination office.",
        "# TYPE agentic_office_transactions_by_office gauge",
    ]

    for office_id, count in office_counts.items():
        lines.append(f'agentic_office_transactions_by_office{{office="{office_id}"}} {count}')

    lines.extend(
        [
            "# HELP agentic_office_rate_limit_config Configured endpoint rate limits.",
            "# TYPE agentic_office_rate_limit_config gauge",
            f'agentic_office_rate_limit_config{{endpoint="message"}} {MESSAGE_RATE_LIMIT}',
            f'agentic_office_rate_limit_config{{endpoint="dispatch-log"}} {DISPATCH_RATE_LIMIT}',
            f'agentic_office_rate_limit_config{{endpoint="request"}} {REQUEST_RATE_LIMIT}',
            "# HELP agentic_office_rate_bucket_events Current in-window events tracked by endpoint.",
            "# TYPE agentic_office_rate_bucket_events gauge",
            f'agentic_office_rate_bucket_events{{endpoint="message"}} {bucket_counts["message"]}',
            f'agentic_office_rate_bucket_events{{endpoint="dispatch-log"}} {bucket_counts["dispatch-log"]}',
            f'agentic_office_rate_bucket_events{{endpoint="request"}} {bucket_counts["request"]}',
        ]
    )

    return "\n".join(lines) + "\n"


@app.get("/capabilities")
async def get_capabilities(_guard: None = Depends(metadata_guard)):
    """Expose office capability map for UI suggestions and orchestration logic."""
    return {"capabilities": OFFICE_CAPABILITIES}


# ---------------------------------------------------------------------------
# Sales Office � Trend Intelligence proxy endpoints
# ---------------------------------------------------------------------------

@app.post("/sales/trends/run")
async def sales_trends_run(request: dict, _auth: str = Depends(rate_limit_dispatch)):
    """
    Proxy: dispatch Leia Organa's trend team via the sales office.
    Body: { keywords: [...], sources?: [...], top_n?: int }
    """
    async with httpx.AsyncClient() as client:
        try:
            resp = await client.post(
                f"{OFFICES['sales']}/trends/run",
                json=request,
                timeout=60.0,
            )
        except Exception as exc:
            raise HTTPException(status_code=502, detail=f"Sales office unreachable: {exc}")
    if resp.status_code != 200:
        raise HTTPException(status_code=resp.status_code, detail=resp.text)
    return resp.json()


@app.post("/sales/trends/quick")
async def sales_trends_quick(request: dict, _auth: str = Depends(rate_limit_dispatch)):
    """Proxy: quick single-keyword trend check via the sales office."""
    async with httpx.AsyncClient() as client:
        try:
            resp = await client.post(
                f"{OFFICES['sales']}/trends/quick",
                json=request,
                timeout=30.0,
            )
        except Exception as exc:
            raise HTTPException(status_code=502, detail=f"Sales office unreachable: {exc}")
    if resp.status_code != 200:
        raise HTTPException(status_code=resp.status_code, detail=resp.text)
    return resp.json()


@app.get("/sales/trends/health")
async def sales_trends_health(_guard: None = Depends(metadata_guard)):
    """Proxy: return sub-agent source health from the sales office."""
    async with httpx.AsyncClient() as client:
        try:
            resp = await client.get(f"{OFFICES['sales']}/trends/health", timeout=10.0)
        except Exception as exc:
            raise HTTPException(status_code=502, detail=f"Sales office unreachable: {exc}")
    if resp.status_code != 200:
        raise HTTPException(status_code=resp.status_code, detail=resp.text)
    return resp.json()


@app.get("/sales/team")
async def sales_team(_guard: None = Depends(metadata_guard)):
    """Proxy: return Leia Organa's full agent roster from the sales office."""
    async with httpx.AsyncClient() as client:
        try:
            resp = await client.get(f"{OFFICES['sales']}/team", timeout=10.0)
        except Exception as exc:
            raise HTTPException(status_code=502, detail=f"Sales office unreachable: {exc}")
    if resp.status_code != 200:
        raise HTTPException(status_code=resp.status_code, detail=resp.text)
    return resp.json()


@app.post("/sales/research/review")
async def sales_research_review(request: dict, _auth: str = Depends(rate_limit_dispatch)):
    """Proxy: Sarah compiles, weights, and routes research reviews for Floor 3 strategy handling."""
    async with httpx.AsyncClient() as client:
        try:
            resp = await client.post(
                f"{OFFICES['sales']}/research/review",
                json=request,
                timeout=30.0,
            )
        except Exception as exc:
            raise HTTPException(status_code=502, detail=f"Sales office unreachable: {exc}")
    if resp.status_code != 200:
        raise HTTPException(status_code=resp.status_code, detail=resp.text)
    return resp.json()



@app.get("/workers")
async def list_workers(_auth: str = Depends(rate_limit_dispatch)):
    """Get all workers organized by floor"""
    session: Session = SessionLocal()
    try:
        workers = session.query(Worker).all()
        workers_by_floor = defaultdict(list)
        for worker in workers:
            workers_by_floor[worker.floor].append({
                "id": worker.worker_id,
                "name": worker.name,
                "email": worker.email,
                "floor": worker.floor,
                "teams": worker.teams,
                "assigned_platforms": worker.assigned_platforms,
                "status": worker.status,
                "role": worker.role,
                "created_at": worker.created_at.isoformat()
            })
        return {"workers": dict(workers_by_floor)}
    finally:
        session.close()


@app.post("/workers/create")
async def create_worker(request: WorkerCreateRequest, _auth: str = Depends(rate_limit_dispatch)):
    """Create a new worker"""
    session: Session = SessionLocal()
    try:
        worker_id = str(uuid.uuid4())
        worker = Worker(
            worker_id=worker_id,
            name=request.name,
            email=request.email,
            floor=request.floor,
            teams=request.teams,
            assigned_platforms=request.assigned_platforms,
            status=request.status,
            role=request.role
        )
        session.add(worker)
        session.commit()
        return {"status": "success", "worker_id": worker_id}
    except Exception as e:
        session.rollback()
        _log_event(logging.ERROR, "worker_creation_failed", error=str(e))
        return {"status": "error", "message": str(e)}
    finally:
        session.close()


@app.post("/workers/{worker_id}/assign-platforms")
async def assign_platforms(worker_id: str, request: WorkerAssignRequest, _auth: str = Depends(rate_limit_dispatch)):
    """Assign platforms to a worker"""
    session: Session = SessionLocal()
    try:
        worker = session.query(Worker).filter(Worker.worker_id == worker_id).first()
        if not worker:
            raise HTTPException(status_code=404, detail="Worker not found")
        
        worker.assigned_platforms = request.platforms
        session.commit()
        return {"status": "success", "assigned_platforms": worker.assigned_platforms}
    except Exception as e:
        session.rollback()
        return {"status": "error", "message": str(e)}
    finally:
        session.close()


@app.post("/workers/{worker_id}/assign-teams")
async def assign_teams(worker_id: str, request: WorkerAssignRequest, _auth: str = Depends(rate_limit_dispatch)):
    """Assign teams to a worker"""
    session: Session = SessionLocal()
    try:
        worker = session.query(Worker).filter(Worker.worker_id == worker_id).first()
        if not worker:
            raise HTTPException(status_code=404, detail="Worker not found")
        
        worker.teams = request.teams
        session.commit()
        return {"status": "success", "teams": worker.teams}
    except Exception as e:
        session.rollback()
        return {"status": "error", "message": str(e)}
    finally:
        session.close()


@app.get("/logs")
async def get_logs(limit: int = 100, _auth: str = Depends(rate_limit_dispatch)):
    """Get transaction logs"""
    if limit < 1:
        raise HTTPException(status_code=400, detail="limit must be >= 1")
    return {"logs": _get_transactions(limit=limit)}


@app.get("/approvals/pending")
async def get_pending_approvals(limit: int = 100, _auth: str = Depends(rate_limit_dispatch)):
    """List requests waiting in the final approval queue."""
    if limit < 1:
        raise HTTPException(status_code=400, detail="limit must be >= 1")
    queued = _get_transactions(limit=limit, action="message", status="needs_final_approval")
    return {"pending_approvals": queued}


@app.post("/approvals/{request_id}/approve")
async def finalize_approval(request_id: int, approval: ApprovalActionRequest, _auth: str = Depends(rate_limit_dispatch)):
    """Approve or reject a request currently waiting for final approval."""
    tx = _get_transaction_by_id(request_id)
    if not tx:
        raise HTTPException(status_code=404, detail="Request not found")

    if tx.get("action") != "message":
        raise HTTPException(status_code=400, detail="Only message workflow requests support final approval")

    if tx.get("status") != "needs_final_approval":
        raise HTTPException(status_code=409, detail="Request is not pending final approval")

    attempts = list(tx.get("attempts") or [])
    attempts.append(
        {
            "role": "final-approver",
            "office": "user",
            "manager": approval.approver,
            "status_code": 200 if approval.approved else 422,
            "notes": approval.notes,
            "timestamp": datetime.utcnow().isoformat(),
        }
    )

    final_status = "completed" if approval.approved else "failed"
    decision = "approved" if approval.approved else "rejected"
    existing_response = dict(tx.get("office_response") or {})
    workflow_summary = list(existing_response.get("workflow") or [])
    existing_final_approval = dict(existing_response.get("final_approval") or {})
    publish_result = None
    existing_response["final_approval"] = {
        **existing_final_approval,
        "required": True,
        "queue_state": "approved" if approval.approved else "rejected",
        "decision": decision,
        "approver": approval.approver,
        "notes": approval.notes,
        "timestamp": datetime.utcnow().isoformat(),
    }

    if approval.approved and existing_response["final_approval"].get("policy") == "social-media-publish":
        publish_result = await _publish_approved_social_campaign(tx.get("instruction", ""), workflow_summary)
        existing_response["publish_execution"] = publish_result
        if publish_result.get("status") != "success":
            final_status = "error"

    updated = _update_transaction(
        request_id,
        {
            "status": final_status,
            "attempts": attempts,
            "office_response": existing_response,
            "error": (
                None
                if approval.approved and final_status == "completed"
                else publish_result.get("message")
                if approval.approved and publish_result
                else "Final approval rejected by user"
            ),
        },
    )

    _log_event(
        logging.INFO if approval.approved else logging.WARNING,
        "final_approval_decision",
        correlation_id=tx.get("correlation_id"),
        request_id=request_id,
        decision=decision,
        approver=approval.approver,
    )

    return {
        "request_id": request_id,
        "status": final_status,
        "decision": decision,
        "publish_result": publish_result,
        "transaction": updated,
    }


@app.get("/")
async def root():
    """Root endpoint - serve the dashboard"""
    static_dir = Path(__file__).parent / "static"
    index_file = static_dir / "index.html"

    if index_file.exists():
        return FileResponse(index_file, media_type="text/html")

    return {
        "service": "Office Orchestrator",
        "version": "1.0.0",
        "dashboard": "/static/index.html",
        "endpoints": {
            "health": "/health",
            "offices": "/offices",
            "request": "/request",
            "message": "/message",
            "logs": "/logs",
            "dispatch_log": "/dispatch-log",
            "stats": "/stats",
            "metrics": "/metrics",
            "capabilities": "/capabilities",
        },
    }


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)



