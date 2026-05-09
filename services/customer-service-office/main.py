"""
Customer Service Office Service

Responsible for:
- Customer support and issue resolution
- Customer satisfaction tracking
- Feedback management
- Service level monitoring
"""
from datetime import datetime

from fastapi import FastAPI

app = FastAPI(title="Customer Service Office", version="1.0.0")


class CustomerServiceOfficeDirector:
    def __init__(self):
        self.name = "C-3PO"
        self.role = "Customer Experience Director"
        self.teams = ["Rapid Response", "Customer Success", "Escalations", "Feedback Intelligence"]
        self.sub_agents = [
            {
                "name": "R2-D2",
                "role": "Rapid Response Lead",
                "source": "service.triage",
                "description": "Prioritizes urgent tickets, outage issues, and immediate service recovery work.",
            },
            {
                "name": "BB-8",
                "role": "Customer Success Specialist",
                "source": "service.success",
                "description": "Owns onboarding follow-ups, proactive outreach, and retention-sensitive support actions.",
            },
            {
                "name": "Maz Kanata",
                "role": "Voice of Customer Analyst",
                "source": "service.feedback",
                "description": "Summarizes complaint themes, praise signals, and recurring customer feedback patterns.",
            },
            {
                "name": "Kuiil",
                "role": "Escalation & Resolution Lead",
                "source": "service.escalation",
                "description": "Handles complex escalations, closure plans, and cross-office service follow-through.",
            },
        ]

    def get_status(self):
        return {
            "manager": self.name,
            "role": self.role,
            "teams": self.teams,
            "sub_agents": self.sub_agents,
        }

    def roster(self):
        return {
            "director": {"name": self.name, "role": self.role},
            "sub_agents": self.sub_agents,
            "teams": self.teams,
        }

    def automated_task_router(self, action: str, payload: dict) -> dict:
        instruction = (payload.get("instruction") or "").strip()
        routes = {
            "rapid_response": ("R2-D2", "Prepare urgent ticket prioritization and immediate customer updates."),
            "customer_success": ("BB-8", "Coordinate onboarding or retention follow-ups and customer success actions."),
            "feedback_intelligence": ("Maz Kanata", "Summarize feedback signals, complaint themes, and service trends."),
            "escalation_resolution": ("Kuiil", "Build an escalation path, owner map, and closure plan."),
        }
        delegated_to, default_response = routes.get(action, (self.name, "Summarize customer-service next steps and response ownership."))

        return {
            "director": self.name,
            "delegated_to": delegated_to,
            "workstream": action,
            "instruction": instruction,
            "response": instruction or default_response,
            "next_steps": [
                "Confirm affected customers, urgency, and communication timing.",
                "Route escalations or product blockers to the right Gamma office owners.",
                "Return customer impact and follow-up actions to the Operations & Propaganda council.",
            ],
        }


manager = CustomerServiceOfficeDirector()


@app.get("/health")
async def health():
    return {"status": "healthy", "office": "customer-service", "timestamp": datetime.utcnow().isoformat()}


@app.get("/manager")
async def get_manager():
    return manager.get_status()


@app.get("/team")
async def get_team():
    return manager.roster()


@app.post("/handle-request")
async def handle_request(request: dict):
    """Handle requests from other offices"""
    action = request.get("action")

    if action == "get_satisfaction_score":
        return {"status": "success", "data": {"nps_score": 72}}
    if action == "get_open_tickets":
        return {"status": "success", "data": {"open_tickets": 45}}
    if action == "rapid_response":
        return {"status": "success", "data": manager.automated_task_router("rapid_response", request)}
    if action == "customer_success":
        return {"status": "success", "data": manager.automated_task_router("customer_success", request)}
    if action == "feedback_intelligence":
        return {"status": "success", "data": manager.automated_task_router("feedback_intelligence", request)}
    if action == "escalation_resolution":
        return {"status": "success", "data": manager.automated_task_router("escalation_resolution", request)}
    if action == "message":
        instruction = (request.get("instruction") or "").strip()
        lower_instruction = instruction.lower()
        delegated_action = "rapid_response"
        if any(token in lower_instruction for token in ["feedback", "complaint trend", "nps", "survey", "voice of customer"]):
            delegated_action = "feedback_intelligence"
        elif any(token in lower_instruction for token in ["onboarding", "success", "retention", "renewal", "follow-up"]):
            delegated_action = "customer_success"
        elif any(token in lower_instruction for token in ["escalation", "vip", "critical", "refund", "angry"]):
            delegated_action = "escalation_resolution"

        routed = manager.automated_task_router(delegated_action, request)
        routed["response"] = "Acknowledged. Customer Service will triage impact, assign follow-ups, and prepare a customer-facing response plan."
        return {"status": "success", "data": routed}

    return {"status": "unknown_action"}


@app.get("/")
async def root():
    return {"service": "Customer Service Office", "manager": manager.get_status()}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
