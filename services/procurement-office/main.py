"""
Procurement Office Service

Responsible for:
- Vendor management
- Purchase order processing
- Supply chain optimization
- Cost management
"""
from datetime import datetime

from fastapi import FastAPI

app = FastAPI(title="Procurement Office", version="1.0.0")


class ProcurementOfficeDirector:
    def __init__(self):
        self.name = "Hondo Ohnaka"
        self.role = "Procurement Director"
        self.teams = ["Vendor Intelligence", "Supplier Relations", "Logistics Control", "Cost Oversight"]
        self.sub_agents = [
            {
                "name": "Wat Tambor",
                "role": "Vendor Intelligence Lead",
                "source": "procurement.vendor",
                "description": "Compares supplier options, quote pressure, and sourcing risk.",
            },
            {
                "name": "Peli Motto",
                "role": "Supplier Relations Lead",
                "source": "procurement.supplier",
                "description": "Handles supplier communication, relationship continuity, and commitment tracking.",
            },
            {
                "name": "Rose Tico",
                "role": "Logistics Control Analyst",
                "source": "procurement.logistics",
                "description": "Reviews lead times, shipping lanes, and fulfillment dependencies.",
            },
            {
                "name": "Nien Nunb",
                "role": "Cost Oversight Coordinator",
                "source": "procurement.cost",
                "description": "Tracks landed cost, margin pressure, and approval-sensitive purchasing tradeoffs.",
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
            "vendor_evaluation": ("Wat Tambor", "Prepare supplier comparison, leverage points, and sourcing risks."),
            "supplier_relations": ("Peli Motto", "Coordinate supplier response, commitment timing, and relationship follow-up."),
            "logistics_control": ("Rose Tico", "Review shipping paths, lead-time exposure, and logistics blockers."),
            "cost_oversight": ("Nien Nunb", "Summarize quote deltas, landed cost, and budget-sensitive tradeoffs."),
        }
        delegated_to, default_response = routes.get(action, (self.name, "Summarize procurement next steps and owner actions."))

        return {
            "director": self.name,
            "delegated_to": delegated_to,
            "workstream": action,
            "instruction": instruction,
            "response": instruction or default_response,
            "next_steps": [
                "Confirm required suppliers and quote windows.",
                "Review logistics timing against launch or fulfillment dependencies.",
                "Return cost and sourcing tradeoffs to the Operations & Propaganda council.",
            ],
        }


manager = ProcurementOfficeDirector()


@app.get("/health")
async def health():
    return {"status": "healthy", "office": "procurement", "timestamp": datetime.utcnow().isoformat()}


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

    if action == "get_vendor_list":
        return {"status": "success", "data": {"vendors": 50}}
    if action == "get_pending_orders":
        return {"status": "success", "data": {"pending_orders": 23}}
    if action == "vendor_evaluation":
        return {"status": "success", "data": manager.automated_task_router("vendor_evaluation", request)}
    if action == "supplier_relations":
        return {"status": "success", "data": manager.automated_task_router("supplier_relations", request)}
    if action == "logistics_control":
        return {"status": "success", "data": manager.automated_task_router("logistics_control", request)}
    if action == "cost_oversight":
        return {"status": "success", "data": manager.automated_task_router("cost_oversight", request)}
    if action == "message":
        instruction = (request.get("instruction") or "").strip()
        lower_instruction = instruction.lower()
        delegated_action = "vendor_evaluation"
        if any(token in lower_instruction for token in ["supplier", "vendor relationship", "renewal", "commitment"]):
            delegated_action = "supplier_relations"
        elif any(token in lower_instruction for token in ["lead time", "ship", "shipping", "logistics", "fulfillment"]):
            delegated_action = "logistics_control"
        elif any(token in lower_instruction for token in ["cost", "quote", "price", "budget", "margin"]):
            delegated_action = "cost_oversight"

        routed = manager.automated_task_router(delegated_action, request)
        routed["response"] = "Acknowledged. Procurement will prepare sourcing options, logistics impacts, and cost tradeoffs for council review."
        return {"status": "success", "data": routed}

    return {"status": "unknown_action"}


@app.get("/")
async def root():
    return {"service": "Procurement Office", "manager": manager.get_status()}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
