"""
THE RESEARCHER — Local Ollama Research Agent

Standalone local-first research agent powered by Ollama.
Designed to run on your PC's resources and eventually slot into
the larger Agentic Office stack via /handle-request.
"""
import logging
import os
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from starlette.middleware.base import BaseHTTPMiddleware

load_dotenv()

from research_agent import ResearchAgent  # noqa: E402 — load_dotenv must run first
import database as db
import scheduler as sched

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

# ── Security ──────────────────────────────────────────────────────────────────

_API_KEY = os.getenv("API_KEY", "").strip()

# Paths accessible without a key (health checks + UI shell)
_OPEN_PATHS = {"/", "/health", "/ui", "/api-config"}


class ApiKeyMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        if not _API_KEY:
            return await call_next(request)
        path = request.url.path
        if path in _OPEN_PATHS or path.startswith("/static"):
            return await call_next(request)
        key = (
            request.headers.get("X-Api-Key")
            or request.headers.get("Authorization", "").removeprefix("Bearer ").strip()
        )
        if key != _API_KEY:
            logger.warning("Rejected request to %s — bad or missing API key from %s", path, request.client)
            return JSONResponse(
                {"status": "error", "message": "Invalid or missing API key"},
                status_code=401,
            )
        return await call_next(request)


@asynccontextmanager
async def lifespan(app: FastAPI):
    db.init_db()
    sched.startup()
    yield
    sched.shutdown()


app = FastAPI(
    title="THE RESEARCHER",
    version="1.0.0",
    description="Local Ollama-powered research agent — web search, Wikipedia, eBay",
    lifespan=lifespan,
)

app.add_middleware(ApiKeyMiddleware)

_static = Path(__file__).parent / "static"
app.mount("/static", StaticFiles(directory=str(_static)), name="static")

agent = ResearchAgent()


# ── Request models ────────────────────────────────────────────────────────────

class ResearchRequest(BaseModel):
    query: str = Field(..., min_length=3, description="What to research")
    max_steps: int = Field(default=10, ge=1, le=20, description="Max tool-use iterations")


class QuickRequest(BaseModel):
    question: str = Field(..., min_length=3, description="Single-shot question")


class ProductResearchRequest(BaseModel):
    query: str = Field(..., min_length=3, description="Product or category to research")
    limit: int = Field(default=12, ge=1, le=20, description="Max eBay listings to fetch and score")


class ScheduleCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=80)
    query: str = Field(..., min_length=3)
    mode: str = Field(default="research", pattern="^(research|products|quick)$")
    schedule_type: str = Field(..., pattern="^(daily|weekly|interval)$")
    schedule_time: str | None = Field(default=None, description="HH:MM in UTC, required for daily/weekly")
    schedule_days: list[str] | None = Field(default=None, description="Days for weekly, e.g. ['mon','fri']")
    interval_hours: int | None = Field(default=None, ge=1, le=168, description="Hours between runs, required for interval")


# ── Endpoints ─────────────────────────────────────────────────────────────────

@app.get("/")
async def root():
    return {
        "service": "THE RESEARCHER",
        "version": "1.0.0",
        "agent": "THE RESEARCHER",
        "ui": "http://localhost:8009/ui",
        "endpoints": {
            "GET  /ui":              "Web interface",
            "POST /research":        "Full agentic research loop (multi-step tool use)",
            "POST /quick":           "Single-shot Q&A (no tools, just the model)",
            "POST /handle-request":  "Orchestrator-compatible routing endpoint",
            "GET  /health":          "Service and model health",
            "GET  /status":          "Agent configuration and model info",
        },
    }


@app.get("/ui")
async def ui():
    return FileResponse(str(_static / "index.html"))


@app.get("/api-config")
async def api_config():
    """Tells the UI whether an API key is required (without revealing the key itself)."""
    return {"requires_key": bool(_API_KEY)}


@app.get("/health")
async def health():
    info = agent.get_model_info()
    status = "healthy" if info.get("status") == "online" and info.get("model_ready") else "degraded"
    return {
        "status": status,
        "office": "researcher",
        "model": info,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


@app.get("/status")
async def status():
    info = agent.get_model_info()
    return {
        "agent": "THE RESEARCHER",
        "role": "Local Ollama Research Agent",
        "model": info,
        "tools": ["web_search", "fetch_page", "wikipedia_search", "thingiverse_search", "ebay_search", "ebay_sold_research"],
        "ebay_configured": bool(os.getenv("EBAY_APP_ID") and os.getenv("EBAY_CERT_ID")),
        "thingiverse_configured": bool(os.getenv("THINGIVERSE_TOKEN")),
        "ollama_url": os.getenv("OLLAMA_URL", "http://localhost:11434"),
    }


@app.post("/research")
async def run_research(request: ResearchRequest):
    """
    Full agentic research loop.
    The agent autonomously searches, reads pages, checks Wikipedia and eBay,
    then synthesizes a structured report.
    """
    logger.info("Research request: %s (max_steps=%d)", request.query[:80], request.max_steps)
    result = await agent.run_async(request.query, max_steps=request.max_steps)
    return {"status": "success", "data": result}


@app.post("/quick")
async def quick_answer(request: QuickRequest):
    """Single-shot Q&A — no tool loop, just a direct model response."""
    answer = await agent.quick_answer_async(request.question)
    return {"status": "success", "answer": answer}


@app.post("/research/products")
async def product_research(request: ProductResearchRequest):
    """
    Product research + recreation ranking pipeline.
    Fetches eBay listings with images/prices, researches sold demand,
    then scores every product 1-10 for recreation potential with Meshy AI.
    Returns products sorted by recreation score, highest first.
    """
    logger.info("Product research: %s (limit=%d)", request.query[:80], request.limit)
    result = await agent.research_and_rank_async(request.query, limit=request.limit)
    return {"status": "success", "data": result}


@app.post("/handle-request")
async def handle_request(request: dict):
    """
    Orchestrator-compatible routing endpoint.
    Mirrors the /handle-request pattern used across the Agentic Office stack.
    """
    action = request.get("action", "")
    instruction = (request.get("instruction") or request.get("query") or "").strip()

    if action in ("message", "research", ""):
        if not instruction:
            return {"status": "error", "message": "instruction or query is required"}
        max_steps = int(request.get("max_steps", 10))
        result = await agent.run_async(instruction, max_steps=max_steps)
        return {"status": "success", "data": result}

    if action == "quick_answer":
        question = (request.get("question") or instruction).strip()
        if not question:
            return {"status": "error", "message": "question or instruction is required"}
        answer = await agent.quick_answer_async(question)
        return {"status": "success", "data": {"answer": answer}}

    if action == "product_research":
        query = (request.get("query") or instruction).strip()
        if not query:
            return {"status": "error", "message": "query is required"}
        limit = int(request.get("limit", 12))
        result = await agent.research_and_rank_async(query, limit=limit)
        return {"status": "success", "data": result}

    if action == "status":
        return {"status": "success", "data": agent.get_model_info()}

    return {
        "status": "unknown_action",
        "available_actions": ["message", "research", "quick_answer", "product_research", "status"],
    }


# ── Schedule endpoints ────────────────────────────────────────────────────────

@app.get("/schedules")
async def list_schedules():
    schedules = db.get_schedules()
    for s in schedules:
        s["next_run"] = sched.get_next_run(s["id"]) or s.get("next_run")
    return {"status": "success", "data": schedules}


@app.post("/schedules")
async def create_schedule(req: ScheduleCreate):
    if req.schedule_type in ("daily", "weekly") and not req.schedule_time:
        raise HTTPException(400, "schedule_time (HH:MM) required for daily/weekly schedules")
    if req.schedule_type == "interval" and not req.interval_hours:
        raise HTTPException(400, "interval_hours required for interval schedules")
    schedule_id = db.create_schedule(
        name=req.name, query=req.query, mode=req.mode,
        schedule_type=req.schedule_type, schedule_time=req.schedule_time,
        schedule_days=req.schedule_days, interval_hours=req.interval_hours,
    )
    schedule = db.get_schedule(schedule_id)
    sched.add_job(schedule)
    return {"status": "success", "data": schedule}


@app.patch("/schedules/{schedule_id}/active")
async def toggle_schedule(schedule_id: int, active: bool):
    schedule = db.get_schedule(schedule_id)
    if not schedule:
        raise HTTPException(404, "Schedule not found")
    db.set_schedule_active(schedule_id, active)
    if active:
        sched.add_job(db.get_schedule(schedule_id))
    else:
        sched.remove_job(schedule_id)
    return {"status": "success", "active": active}


@app.delete("/schedules/{schedule_id}")
async def delete_schedule(schedule_id: int):
    if not db.get_schedule(schedule_id):
        raise HTTPException(404, "Schedule not found")
    sched.remove_job(schedule_id)
    db.delete_schedule(schedule_id)
    return {"status": "success"}


# ── Report endpoints ──────────────────────────────────────────────────────────

@app.get("/reports")
async def list_reports():
    return {"status": "success", "data": db.get_reports()}


@app.get("/reports/{report_id}")
async def get_report(report_id: int):
    report = db.get_report(report_id)
    if not report:
        raise HTTPException(404, "Report not found")
    return {"status": "success", "data": report}


@app.delete("/reports/{report_id}")
async def delete_report(report_id: int):
    if not db.get_report(report_id):
        raise HTTPException(404, "Report not found")
    db.delete_report(report_id)
    return {"status": "success"}


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", "8009"))
    host = os.getenv("HOST", "127.0.0.1")  # localhost-only by default; set HOST=0.0.0.0 only if behind a trusted proxy
    uvicorn.run("main:app", host=host, port=port, reload=False)
