"""
HR Office Service

Responsible for:
- Recruitment and hiring
- Employee records management
- Payroll and benefits
- Organizational development
"""
from fastapi import FastAPI
from datetime import datetime
from typing import Any
import re
import sys
import os

# Add shared libs to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../../'))

from shared.libs import get_llm_client, generate_office_decision, OfficePromptsFactory

app = FastAPI(title="HR Office", version="1.0.0")

# Initialize LLM client
llm_client = get_llm_client()

class HRSubAgent:
    agent_name = "HR Sub-Agent"
    agent_role = "Specialist"
    agent_source = "internal"
    description = ""

    def identity(self) -> dict[str, str]:
        return {
            "name": self.agent_name,
            "role": self.agent_role,
            "source": self.agent_source,
            "description": self.description,
        }


class RecruitmentAgent(HRSubAgent):
    agent_name = "Ahsoka Tano"
    agent_role = "Recruitment Lead"
    description = "Evaluates candidates, recruiting fit, and hiring recommendations."

    def run(self, director: "HROfficeDirector", position: str, candidate_info: str) -> str:
        return generate_office_decision(
            office_type="hr",
            decision_type="candidate_evaluation",
            llm_client=director.llm_client,
            position=position,
            candidate_info=candidate_info,
        )


class PerformanceAgent(HRSubAgent):
    agent_name = "Captain Rex"
    agent_role = "Employee Performance Specialist"
    description = "Handles performance cases and coaching/escalation recommendations."

    def run(self, director: "HROfficeDirector", performance_info: str) -> str:
        return generate_office_decision(
            office_type="hr",
            decision_type="employee_performance",
            llm_client=director.llm_client,
            performance_info=performance_info,
        )


class PolicyAgent(HRSubAgent):
    agent_name = "Padme Amidala"
    agent_role = "Policy & Compliance Specialist"
    description = "Drafts HR policy recommendations and compliance-aligned guidance."

    def run(self, director: "HROfficeDirector", topic: str, context: str) -> str:
        return generate_office_decision(
            office_type="hr",
            decision_type="policy_recommendation",
            llm_client=director.llm_client,
            topic=topic,
            context=context,
        )


class IntegrityReviewerAgent(HRSubAgent):
    agent_name = "Obi-Wan Kenobi"
    agent_role = "Integrity Reviewer"
    description = "Reviews text for offensiveness, grossness, and professionalism risk before release."

    def run(self, director: "HROfficeDirector", content: str) -> dict[str, Any]:
        text = (content or "").lower()
        offensive_patterns = [
            r"\bhate\b", r"\bracist\b", r"\bsexist\b", r"\bslur\b", r"\boffensive\b", r"\bexplicit\b",
        ]
        gross_patterns = [
            r"\bgross\b", r"\bdisgusting\b", r"\bvomit\b", r"\bfeces\b", r"\bbodily fluid\b",
        ]

        offensive_hits = [pat for pat in offensive_patterns if re.search(pat, text)]
        gross_hits = [pat for pat in gross_patterns if re.search(pat, text)]
        risk_score = min(1.0, (len(offensive_hits) * 0.3) + (len(gross_hits) * 0.25))

        if risk_score >= 0.5:
            verdict = "high_risk"
            recommendation = "Block or rewrite before approval."
        elif risk_score >= 0.2:
            verdict = "moderate_risk"
            recommendation = "Revise tone and remove risky language before release."
        else:
            verdict = "low_risk"
            recommendation = "Content is acceptable for normal workflow review."

        opinion_prompt = (
            "You are an HR Integrity Reviewer. Give a brief professionalism opinion in 2 bullet points.\n"
            f"Content:\n{content}\n"
            f"Detected risk score: {round(risk_score, 3)}"
        )
        try:
            opinion = director.llm_client.generate(opinion_prompt, "Review for offensiveness and grossness risk.")
        except Exception:
            opinion = (
                "- Content reviewed for offensive and gross language.\n"
                f"- Recommended action: {recommendation}"
            )

        return {
            "verdict": verdict,
            "risk_score": round(risk_score, 3),
            "offensive_hits": len(offensive_hits),
            "gross_hits": len(gross_hits),
            "recommendation": recommendation,
            "opinion": opinion,
        }


class HROfficeDirector:
    def __init__(self):
        self.name = "General Organa"
        self.role = "HR Director"
        self.teams = ["Recruitment", "Employee Relations", "Payroll", "Benefits", "Integrity Review"]
        self.llm_client = llm_client
        self._recruitment_agent = RecruitmentAgent()
        self._performance_agent = PerformanceAgent()
        self._policy_agent = PolicyAgent()
        self._integrity_agent = IntegrityReviewerAgent()

    def roster(self) -> dict[str, Any]:
        return {
            "director": {"name": self.name, "role": self.role},
            "sub_agents": [
                self._recruitment_agent.identity(),
                self._performance_agent.identity(),
                self._policy_agent.identity(),
                self._integrity_agent.identity(),
            ],
        }

    def get_status(self):
        return {
            "manager": self.name,
            "role": self.role,
            "teams": self.teams,
            "llm_status": self.llm_client.get_status(),
            "task_director": "enabled",
            "sub_agent_count": 4,
        }

    def evaluate_candidate(self, position: str, candidate_info: str) -> str:
        try:
            return self._recruitment_agent.run(self, position=position, candidate_info=candidate_info)
        except Exception as e:
            return f"Error evaluating candidate: {str(e)}"

    def handle_employee_performance(self, performance_info: str) -> str:
        try:
            return self._performance_agent.run(self, performance_info=performance_info)
        except Exception as e:
            return f"Error handling performance: {str(e)}"

    def create_hr_policy(self, topic: str, context: str) -> str:
        try:
            return self._policy_agent.run(self, topic=topic, context=context)
        except Exception as e:
            return f"Error creating policy: {str(e)}"

    def integrity_review(self, content: str) -> dict[str, Any]:
        return self._integrity_agent.run(self, content)

    def respond_to_message(self, instruction: str) -> str:
        try:
            system_prompt = OfficePromptsFactory.get_system_prompt("hr")
            return self.llm_client.generate(instruction, system_prompt)
        except Exception as e:
            return f"Error handling message: {str(e)}"

    def automated_task_router(self, action: str, payload: dict[str, Any]) -> dict[str, Any]:
        """Director-level automatic delegation plus mandatory integrity opinion stage."""
        if action == "evaluate_candidate":
            position = payload.get("position", "")
            candidate_info = payload.get("candidate_info", "")
            return {
                "status": "success",
                "delegated_to": self._recruitment_agent.identity(),
                "evaluation": self.evaluate_candidate(position, candidate_info),
                "integrity_review": self.integrity_review(candidate_info),
            }

        if action == "employee_performance":
            performance_info = payload.get("performance_info", "")
            return {
                "status": "success",
                "delegated_to": self._performance_agent.identity(),
                "decision": self.handle_employee_performance(performance_info),
                "integrity_review": self.integrity_review(performance_info),
            }

        if action == "create_policy":
            topic = payload.get("topic", "")
            context = payload.get("context", "")
            combined = f"{topic}\n{context}".strip()
            return {
                "status": "success",
                "delegated_to": self._policy_agent.identity(),
                "policy": self.create_hr_policy(topic, context),
                "integrity_review": self.integrity_review(combined),
            }

        if action == "integrity_review":
            content = payload.get("content", "")
            return {
                "status": "success",
                "delegated_to": self._integrity_agent.identity(),
                "integrity_review": self.integrity_review(content),
            }

        if action == "message":
            instruction = (payload.get("instruction") or "").strip()
            return {
                "status": "success",
                "delegated_to": {
                    "name": self.name,
                    "role": self.role,
                    "source": "director",
                    "description": "Director-level free-form response",
                },
                "response": self.respond_to_message(instruction),
                "integrity_review": self.integrity_review(instruction),
            }

        return {"status": "unknown_action"}

manager = HROfficeDirector()


@app.get("/health")
async def health():
    return {"status": "healthy", "office": "hr", "timestamp": datetime.utcnow().isoformat()}


@app.get("/manager")
async def get_manager():
    return {**manager.get_status(), "team": manager.roster()}


@app.get("/team")
async def get_team():
    return {
        "status": "success",
        "office": "HR Office",
        **manager.roster(),
    }


@app.post("/evaluate-candidate")
async def evaluate_candidate(request: dict):
    """Evaluate job candidates using AI"""
    position = request.get("position", "")
    candidate_info = request.get("candidate_info", "")
    
    if not position or not candidate_info:
        return {"status": "error", "message": "position and candidate_info required"}
    
    routed = manager.automated_task_router("evaluate_candidate", {
        "position": position,
        "candidate_info": candidate_info,
    })
    return {"status": "success", **routed}


@app.post("/employee-performance")
async def employee_performance(request: dict):
    """Handle employee performance issues using AI"""
    performance_info = request.get("performance_info", "")
    
    if not performance_info:
        return {"status": "error", "message": "performance_info required"}
    
    routed = manager.automated_task_router("employee_performance", {
        "performance_info": performance_info,
    })
    return {"status": "success", **routed}


@app.post("/create-policy")
async def create_policy(request: dict):
    """Create HR policies using AI"""
    topic = request.get("topic", "")
    context = request.get("context", "")
    
    if not topic:
        return {"status": "error", "message": "topic required"}
    
    routed = manager.automated_task_router("create_policy", {
        "topic": topic,
        "context": context,
    })
    return {"status": "success", **routed}


@app.post("/integrity-review")
async def integrity_review(request: dict):
    """Mandatory HR integrity opinion on offensiveness/grossness/professionalism."""
    content = (request.get("content") or "").strip()
    if not content:
        return {"status": "error", "message": "content required"}
    return {
        "status": "success",
        "review": manager.integrity_review(content),
    }


@app.post("/handle-request")
async def handle_request(request: dict):
    """Handle requests from other offices"""
    action = request.get("action")
    
    if action == "get_employee_count":
        return {"status": "success", "data": {"total_employees": 150}}
    elif action == "get_salary_budget":
        return {"status": "success", "data": {"budget": 5000000}}
    elif action == "evaluate_candidate":
        candidate_info = request.get("candidate_info", "")
        position = request.get("position", "unknown")
        routed = manager.automated_task_router("evaluate_candidate", {
            "position": position,
            "candidate_info": candidate_info,
        })
        return {"status": "success", "data": routed}
    elif action == "employee_performance":
        performance_info = request.get("performance_info", "")
        routed = manager.automated_task_router("employee_performance", {
            "performance_info": performance_info,
        })
        return {"status": "success", "data": routed}
    elif action == "create_policy":
        topic = request.get("topic", "")
        context = request.get("context", "")
        routed = manager.automated_task_router("create_policy", {
            "topic": topic,
            "context": context,
        })
        return {"status": "success", "data": routed}
    elif action == "integrity_review":
        content = request.get("content", "")
        routed = manager.automated_task_router("integrity_review", {
            "content": content,
        })
        return {"status": "success", "data": routed}
    elif action == "message":
        instruction = (request.get("instruction") or "").strip()
        if not instruction:
            return {"status": "error", "message": "instruction required"}
        routed = manager.automated_task_router("message", {
            "instruction": instruction,
        })
        return {"status": "success", "data": routed}
    
    return {"status": "unknown_action"}


@app.get("/")
async def root():
    return {
        "service": "HR Office",
        "version": "1.0.0",
        "description": "AI-powered HR management and recruitment"
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)

