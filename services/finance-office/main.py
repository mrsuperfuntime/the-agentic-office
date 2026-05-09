"""
Finance Office Service

Responsible for:
- Budgeting and financial planning
- Financial reporting and analysis
- Cost control and investments
- Organizational fiscal strategy
"""
from fastapi import FastAPI
from datetime import datetime
from typing import Any
import sys
import os

# Add shared libs to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../../'))

from shared.libs import get_llm_client, generate_office_decision, OfficePromptsFactory

app = FastAPI(title="Finance Office", version="1.0.0")

# Initialize LLM client
llm_client = get_llm_client()


class FinanceSubAgent:
    agent_name = "Finance Sub-Agent"
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


class BudgetPlanningAgent(FinanceSubAgent):
    agent_name = "Bail Organa"
    agent_role = "Budget Planning Lead"
    description = "Evaluates budget requests, allocations, and planning scenarios."

    def run(self, director: "FinanceOfficeDirector", request_details: str, budget_info: str) -> str:
        return generate_office_decision(
            office_type="finance",
            decision_type="budget_analysis",
            llm_client=director.llm_client,
            request_details=request_details,
            budget_info=budget_info,
        )


class FinancialHealthAgent(FinanceSubAgent):
    agent_name = "Mon Mothma"
    agent_role = "Financial Health Analyst"
    description = "Assesses cashflow resilience, risk posture, and financial sustainability."

    def run(self, director: "FinanceOfficeDirector", financial_data: str) -> str:
        return generate_office_decision(
            office_type="finance",
            decision_type="financial_health",
            llm_client=director.llm_client,
            financial_data=financial_data,
        )


class ExpenseControlAgent(FinanceSubAgent):
    agent_name = "Admiral Ackbar"
    agent_role = "Expense Control Lead"
    description = "Reviews spending efficiency and identifies cost optimization opportunities."

    def run(self, director: "FinanceOfficeDirector", expenses: str) -> str:
        return generate_office_decision(
            office_type="finance",
            decision_type="expense_review",
            llm_client=director.llm_client,
            expenses=expenses,
        )


class FinanceOfficeDirector:
    def __init__(self):
        self.name = "Mace Windu"
        self.role = "Finance Director"
        self.teams = ["Accounting", "Planning", "Analysis", "Audit"]
        self.llm_client = llm_client
        self._budget_agent = BudgetPlanningAgent()
        self._health_agent = FinancialHealthAgent()
        self._expense_agent = ExpenseControlAgent()

    def roster(self) -> dict[str, Any]:
        return {
            "director": {"name": self.name, "role": self.role},
            "sub_agents": [
                self._budget_agent.identity(),
                self._health_agent.identity(),
                self._expense_agent.identity(),
            ],
        }

    def get_status(self):
        return {
            "manager": self.name,
            "role": self.role,
            "teams": self.teams,
            "llm_status": self.llm_client.get_status(),
            "task_director": "enabled",
            "sub_agent_count": 3,
        }

    def analyze_budget_request(self, request_details: str, budget_info: str) -> str:
        try:
            return self._budget_agent.run(self, request_details=request_details, budget_info=budget_info)
        except Exception as e:
            return f"Error analyzing budget: {str(e)}"

    def assess_financial_health(self, financial_data: str) -> str:
        try:
            return self._health_agent.run(self, financial_data=financial_data)
        except Exception as e:
            return f"Error assessing financial health: {str(e)}"

    def analyze_expenses(self, expenses: str) -> str:
        try:
            return self._expense_agent.run(self, expenses=expenses)
        except Exception as e:
            return f"Error analyzing expenses: {str(e)}"

    def respond_to_message(self, instruction: str) -> str:
        try:
            system_prompt = OfficePromptsFactory.get_system_prompt("finance")
            return self.llm_client.generate(instruction, system_prompt)
        except Exception as e:
            return f"Error handling message: {str(e)}"

    def automated_task_router(self, action: str, payload: dict[str, Any]) -> dict[str, Any]:
        """Director-level automatic delegation to specialist finance sub-agents."""
        if action == "analyze_budget":
            request_details = payload.get("request_details", "")
            budget_info = payload.get("budget_info", "")
            return {
                "status": "success",
                "delegated_to": self._budget_agent.identity(),
                "analysis": self.analyze_budget_request(request_details, budget_info),
            }

        if action == "financial_health":
            financial_data = payload.get("financial_data", "")
            return {
                "status": "success",
                "delegated_to": self._health_agent.identity(),
                "assessment": self.assess_financial_health(financial_data),
            }

        if action == "analyze_expenses":
            expenses = payload.get("expenses", "")
            return {
                "status": "success",
                "delegated_to": self._expense_agent.identity(),
                "analysis": self.analyze_expenses(expenses),
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
            }

        return {"status": "unknown_action"}


manager = FinanceOfficeDirector()


@app.get("/health")
async def health():
    return {"status": "healthy", "office": "finance", "timestamp": datetime.utcnow().isoformat()}


@app.get("/manager")
async def get_manager():
    return {**manager.get_status(), "team": manager.roster()}


@app.get("/team")
async def get_team():
    return {
        "status": "success",
        "office": "Finance Office",
        **manager.roster(),
    }


@app.post("/analyze-budget")
async def analyze_budget(request: dict):
    """Analyze budget requests using AI"""
    request_details = request.get("request_details", "")
    budget_info = request.get("budget_info", "")
    
    if not request_details:
        return {"status": "error", "message": "request_details required"}
    
    routed = manager.automated_task_router("analyze_budget", {
        "request_details": request_details,
        "budget_info": budget_info,
    })
    return {"status": "success", **routed}


@app.post("/financial-health")
async def financial_health(request: dict):
    """Assess financial health using AI"""
    financial_data = request.get("financial_data", "")
    
    if not financial_data:
        return {"status": "error", "message": "financial_data required"}
    
    routed = manager.automated_task_router("financial_health", {
        "financial_data": financial_data,
    })
    return {"status": "success", **routed}


@app.post("/analyze-expenses")
async def analyze_expenses(request: dict):
    """Analyze expenses using AI"""
    expenses = request.get("expenses", "")
    
    if not expenses:
        return {"status": "error", "message": "expenses required"}
    
    routed = manager.automated_task_router("analyze_expenses", {
        "expenses": expenses,
    })
    return {"status": "success", **routed}


@app.post("/handle-request")
async def handle_request(request: dict):
    """Handle requests from other offices"""
    action = request.get("action")
    
    if action == "get_budget":
        return {"status": "success", "data": {"available_budget": 5000000}}
    elif action == "analyze_budget":
        request_details = request.get("request_details", "")
        budget_info = request.get("budget_info", "")
        analysis = manager.analyze_budget_request(request_details, budget_info)
        return {"status": "success", "data": {"analysis": analysis}}
    elif action == "get_financial_report":
        return {"status": "success", "data": {"quarterly_revenue": 2500000, "expenses": 1500000}}
    elif action == "message":
        instruction = (request.get("instruction") or "").strip()
        if not instruction:
            return {"status": "error", "message": "instruction required"}
        routed = manager.automated_task_router("message", {"instruction": instruction})
        return {"status": "success", "data": routed}
    elif action in {"analyze_budget", "financial_health", "analyze_expenses"}:
        routed = manager.automated_task_router(action, request)
        return {"status": "success", "data": routed}
    
    return {"status": "unknown_action"}


@app.get("/")
async def root():
    return {
        "service": "Finance Office",
        "version": "1.0.0",
        "description": "AI-powered financial management and analysis"
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)

