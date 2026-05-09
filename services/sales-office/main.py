"""
Sales Office Service

Manager: Leia Organa (Sales Office Manager)

Responsible for:
- Sales pipeline management
- Deal tracking and forecasting
- Customer acquisition
- Revenue forecasting
- Trend intelligence (Reddit, YouTube, Google Trends, Etsy, MakerWorld)
  coordinated through Leia's specialist sub-agent team
"""
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field
from datetime import datetime
from typing import Optional, Any
import sys
import os
import re

# Add shared libs to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../../'))

from shared.libs import get_llm_client, generate_office_decision, OfficePromptsFactory
from trend_agent import TrendIntelligenceAgent

app = FastAPI(title="Sales Office", version="1.0.0")

# Initialize LLM client
llm_client = get_llm_client()

# Office Manager � Leia Organa
class SalesOfficeManager:
    def __init__(self):
        self.name = "Leia Organa"
        self.role = "Sales Office Manager"
        self.teams = ["Account Executives", "Sales Development", "Sales Operations", "Trend Intelligence"]
        self.llm_client = llm_client
    
    def get_status(self):
        return {
            "manager": self.name,
            "role": self.role,
            "teams": self.teams,
            "llm_status": self.llm_client.get_status()
        }
    
    def analyze_prospect(self, prospect_data: str) -> str:
        """Use AI to analyze prospects"""
        try:
            return generate_office_decision(
                office_type="sales",
                decision_type="prospect_scoring",
                llm_client=self.llm_client,
                prospects=prospect_data
            )
        except Exception as e:
            return f"Error analyzing prospect: {str(e)}"
    
    def forecast_revenue(self, period: str, deals: str) -> str:
        """Use AI to forecast revenue"""
        try:
            return generate_office_decision(
                office_type="sales",
                decision_type="forecast_revenue",
                llm_client=self.llm_client,
                period=period,
                deals=deals
            )
        except Exception as e:
            return f"Error forecasting revenue: {str(e)}"
    
    def analyze_deal(self, deal_info: str) -> str:
        """Use AI to analyze a sales deal"""
        try:
            return generate_office_decision(
                office_type="sales",
                decision_type="analyze_deal",
                llm_client=self.llm_client,
                deal_info=deal_info
            )
        except Exception as e:
            return f"Error analyzing deal: {str(e)}"

    def respond_to_message(self, instruction: str) -> str:
        """Use AI to respond to free-form office instructions."""
        try:
            system_prompt = OfficePromptsFactory.get_system_prompt("sales")
            return self.llm_client.generate(instruction, system_prompt)
        except Exception as e:
            return f"Error handling message: {str(e)}"

manager = SalesOfficeManager()

# Trend Intelligence Agent (shared LLM client)
trend_agent = TrendIntelligenceAgent(llm_client)


class TrendRunRequest(BaseModel):
    keywords: list[str]
    sources: Optional[list[str]] = None
    top_n: int = 5


class ResearchReviewRequest(BaseModel):
    request_text: str = Field(..., min_length=5)
    keywords: list[str] = Field(default_factory=list)
    metrics: dict[str, float] = Field(default_factory=dict)
    trend_report: dict[str, Any] | None = None
    requested_by: str = "user"


def _clamp01(value: float) -> float:
    return max(0.0, min(1.0, value))


def _metric(metrics: dict[str, float], key: str, fallback: float) -> float:
    raw = metrics.get(key)
    if raw is None:
        return _clamp01(fallback)
    try:
        return _clamp01(float(raw))
    except Exception:
        return _clamp01(fallback)


def _infer_metrics(request_text: str, keywords: list[str], trend_report: dict[str, Any] | None, metrics: dict[str, float]) -> dict[str, float]:
    lowered = request_text.lower()
    keyword_count = len([k for k in keywords if str(k).strip()])

    top_clusters = (trend_report or {}).get("top_clusters") or []
    if top_clusters:
        avg_composite = sum(float(c.get("composite_score", 0)) for c in top_clusters[:5]) / min(len(top_clusters), 5)
        trend_strength_fallback = _clamp01(avg_composite / 100.0)
    else:
        trend_strength_fallback = 0.45

    relevance_fallback = _clamp01(0.35 + (keyword_count * 0.08))

    cost_terms = ["budget", "cost", "spend", "pricing", "cpc", "ad spend", "roi", "margin"]
    hr_terms = ["employee", "hiring", "policy", "harassment", "bias", "discrimination", "compliance"]
    offensive_terms = ["slur", "hate", "racist", "sexist", "offensive", "vulgar", "explicit"]
    gross_terms = ["gross", "disgusting", "nasty", "vomit", "feces"]

    def term_hits(terms: list[str]) -> int:
        return sum(1 for t in terms if t in lowered)

    cost_risk_fallback = _clamp01(0.15 + (term_hits(cost_terms) * 0.15))
    hr_risk_fallback = _clamp01(0.10 + (term_hits(hr_terms) * 0.18))
    safety_risk_fallback = _clamp01((term_hits(offensive_terms) * 0.25) + (term_hits(gross_terms) * 0.20))

    return {
        "relevance": _metric(metrics, "relevance", relevance_fallback),
        "trend_strength": _metric(metrics, "trend_strength", trend_strength_fallback),
        "cost_risk": _metric(metrics, "cost_risk", cost_risk_fallback),
        "hr_risk": _metric(metrics, "hr_risk", hr_risk_fallback),
        "safety_risk": _metric(metrics, "safety_risk", safety_risk_fallback),
    }


def _routing_recommendation(cost_risk: float, hr_risk: float, safety_risk: float) -> dict[str, str | list[str]]:
    if safety_risk >= 0.4:
        return {
            "route_to": ["hr", "finance"],
            "primary_reviewer": "HR Manager",
            "reason": "Potentially offensive or gross content requires HR review before commercial execution.",
        }
    if hr_risk >= 0.45 and cost_risk >= 0.45:
        return {
            "route_to": ["hr", "finance"],
            "primary_reviewer": "HR + Finance",
            "reason": "Both workforce/compliance and cost impacts are elevated.",
        }
    if hr_risk >= 0.45:
        return {
            "route_to": ["hr"],
            "primary_reviewer": "HR Manager",
            "reason": "Workforce or policy risk is elevated.",
        }
    return {
        "route_to": ["finance"],
        "primary_reviewer": "Finance Director",
        "reason": "Primary concern is cost efficiency and expected return.",
    }


def _llm_research_summary(packet: dict[str, Any]) -> str:
    prompt = (
        "Summarize this sales research review in 4 bullet points for a Floor 3 strategy panel. "
        "Include weighted opportunity score, key risks, and why it was routed to the selected reviewer.\n\n"
        f"Request: {packet['request_text']}\n"
        f"Keywords: {', '.join(packet['keywords'])}\n"
        f"Weighted scores: {packet['weighted_scores']}\n"
        f"Risk flags: {packet['risk_flags']}\n"
        f"Route: {packet['routing']}"
    )
    try:
        return manager.llm_client.generate(prompt, "You are Leia Organa, Sales Office Manager.")
    except Exception:
        return (
            "- Sarah consolidated the research request and computed weighted opportunity/risk scores.\n"
            f"- Opportunity score: {packet['weighted_scores']['opportunity_score']} / 100.\n"
            f"- Risk score: {packet['weighted_scores']['risk_score']} / 100 with flags: {', '.join(packet['risk_flags']) or 'none'}.\n"
            f"- Routed to {', '.join(packet['routing']['route_to'])} for Floor 3 review."
        )


def build_research_review_packet(request: ResearchReviewRequest) -> dict[str, Any]:
    inferred = _infer_metrics(request.request_text, request.keywords, request.trend_report, request.metrics)

    relevance = inferred["relevance"]
    trend_strength = inferred["trend_strength"]
    cost_risk = inferred["cost_risk"]
    hr_risk = inferred["hr_risk"]
    safety_risk = inferred["safety_risk"]

    opportunity_score = round(100 * ((0.35 * relevance) + (0.35 * trend_strength) + (0.20 * (1 - cost_risk)) + (0.10 * (1 - hr_risk))), 1)
    risk_score = round(100 * ((0.45 * cost_risk) + (0.35 * hr_risk) + (0.20 * safety_risk)), 1)

    risk_flags: list[str] = []
    if cost_risk >= 0.45:
        risk_flags.append("cost")
    if hr_risk >= 0.45:
        risk_flags.append("hr")
    if safety_risk >= 0.35:
        risk_flags.append("offensive_or_gross")

    routing = _routing_recommendation(cost_risk, hr_risk, safety_risk)

    packet: dict[str, Any] = {
        "manager": manager.name,
        "manager_role": manager.role,
        "requested_by": request.requested_by,
        "request_text": request.request_text,
        "keywords": request.keywords,
        "weighted_scores": {
            "relevance": round(relevance, 3),
            "trend_strength": round(trend_strength, 3),
            "cost_risk": round(cost_risk, 3),
            "hr_risk": round(hr_risk, 3),
            "safety_risk": round(safety_risk, 3),
            "opportunity_score": opportunity_score,
            "risk_score": risk_score,
        },
        "risk_flags": risk_flags,
        "routing": {
            **routing,
            "target_panel": "floor_3_strategy_review",
            "recommended_step": "Review by Finance/HR before execution",
        },
        "generated_at": datetime.utcnow().isoformat(),
    }
    packet["summary"] = _llm_research_summary(packet)
    return packet


@app.get("/health")
async def health():
    return {"status": "healthy", "office": "sales", "timestamp": datetime.utcnow().isoformat()}


@app.get("/manager")
async def get_manager():
    return {
        **manager.get_status(),
        "trend_team": trend_agent.roster(),
    }


@app.get("/team")
async def get_team():
    """Return Leia Organa's full agent roster including trend sub-agents."""
    return {
        "status": "success",
        "office": "Sales Office",
        **trend_agent.roster(),
    }


@app.post("/analyze-prospect")
async def analyze_prospect(request: dict):
    """Analyze prospects using AI"""
    prospect_data = request.get("prospect_data", "")
    if not prospect_data:
        return {"status": "error", "message": "prospect_data required"}
    
    analysis = manager.analyze_prospect(prospect_data)
    return {"status": "success", "analysis": analysis}


@app.post("/forecast-revenue")
async def forecast_revenue(request: dict):
    """Forecast revenue using AI"""
    period = request.get("period", "Q4")
    deals = request.get("deals", "")
    
    forecast = manager.forecast_revenue(period, deals)
    return {"status": "success", "forecast": forecast}


@app.post("/analyze-deal")
async def analyze_deal(request: dict):
    """Analyze a sales deal using AI"""
    deal_info = request.get("deal_info", "")
    if not deal_info:
        return {"status": "error", "message": "deal_info required"}
    
    analysis = manager.analyze_deal(deal_info)
    return {"status": "success", "analysis": analysis}


@app.post("/handle-request")
async def handle_request(request: dict):
    """Handle requests from other offices"""
    action = request.get("action")
    
    if action == "get_pipeline":
        return {"status": "success", "data": {"pipeline_value": 1500000}}
    elif action == "get_forecast":
        forecast = manager.forecast_revenue("Q4", "Current pipeline")
        return {"status": "success", "data": {"forecast": forecast}}
    elif action == "analyze_prospects":
        prospects = request.get("prospects", "")
        analysis = manager.analyze_prospect(prospects)
        return {"status": "success", "data": {"analysis": analysis}}
    elif action == "message":
        instruction = (request.get("instruction") or "").strip()
        if not instruction:
            return {"status": "error", "message": "instruction required"}
        response = manager.respond_to_message(instruction)
        return {"status": "success", "data": {"response": response}}
    elif action == "trend_run":
        keywords = request.get("keywords") or []
        if not keywords:
            return {"status": "error", "message": "keywords required"}
        report = trend_agent.run(
            keywords=keywords,
            sources=request.get("sources"),
            top_n=int(request.get("top_n", 5)),
        )
        return {"status": "success", "data": report.to_dict()}
    elif action == "research_review":
        request_text = (request.get("request_text") or "").strip()
        if not request_text:
            return {"status": "error", "message": "request_text required"}
        payload = ResearchReviewRequest(
            request_text=request_text,
            keywords=request.get("keywords") or [],
            metrics=request.get("metrics") or {},
            trend_report=request.get("trend_report"),
            requested_by=request.get("requested_by") or "orchestrator",
        )
        return {"status": "success", "data": build_research_review_packet(payload)}
    
    return {"status": "unknown_action"}


@app.get("/")
async def root():
    return {
        "service": "Sales Office",
        "version": "1.0.0",
        "description": "AI-powered sales management, forecasting, and trend intelligence"
    }


# ---------------------------------------------------------------------------
# Trend Intelligence endpoints
# ---------------------------------------------------------------------------

@app.post("/trends/run")
async def trends_run(request: TrendRunRequest):
    """
    Execute the full trend intelligence pipeline.

    Body:
        keywords  � list of keywords/phrases to analyse
        sources   � optional subset: reddit, youtube, google_trends, etsy, makerworld
        top_n     � how many top clusters to include (default 5)
    """
    if not request.keywords:
        raise HTTPException(status_code=422, detail="At least one keyword is required")
    if len(request.keywords) > 20:
        raise HTTPException(status_code=422, detail="Maximum 20 keywords per run")

    report = trend_agent.run(
        keywords=request.keywords,
        sources=request.sources,
        top_n=request.top_n,
    )
    return {"status": "success", "report": report.to_dict()}


@app.get("/trends/health")
async def trends_health():
    """Return configured / degraded status for each signal source."""
    return {
        "status": "success",
        "source_health": trend_agent.get_source_health(),
    }


@app.post("/trends/quick")
async def trends_quick(request: dict):
    """
    Lightweight trend check � runs a single keyword against all sources
    and returns the top cluster + LLM ideas only.
    """
    keyword = (request.get("keyword") or "").strip()
    if not keyword:
        raise HTTPException(status_code=422, detail="keyword is required")

    report = trend_agent.run(keywords=[keyword], top_n=1)
    top = report.top_clusters[0].to_dict() if report.top_clusters else {}
    return {
        "status": "success",
        "keyword": keyword,
        "top_cluster": top,
        "ideas": report.ideas,
        "alerts": report.alerts,
        "recommended_actions": report.recommended_actions,
    }


@app.post("/research/review")
async def research_review(request: ResearchReviewRequest):
    """
    Leia Organa compiles and weights a research request, flags risk domains,
    and routes the output to the most appropriate Floor 3 reviewer.
    """
    packet = build_research_review_packet(request)
    return {
        "status": "success",
        "review_packet": packet,
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)



