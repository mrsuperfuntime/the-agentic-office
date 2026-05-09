"""
Manufacturing Office Service

Responsible for:
- Production scheduling
- Quality assurance
- Inventory management
- Operational efficiency
"""
from datetime import datetime

from fastapi import FastAPI

app = FastAPI(title="Manufacturing Office", version="1.0.0")


class ManufacturingOfficeDirector:
    def __init__(self):
        self.name = "Galen Erso"
        self.role = "Manufacturing Director"
        self.teams = ["Production Planning", "Throughput Ops", "Inventory Systems", "Quality Command"]
        self.sub_agents = [
            {
                "name": "Tech",
                "role": "Production Planning Lead",
                "source": "manufacturing.plan",
                "description": "Builds schedules, line plans, and capacity scenarios.",
            },
            {
                "name": "Wrecker",
                "role": "Throughput Operations Lead",
                "source": "manufacturing.ops",
                "description": "Handles bottlenecks, throughput spikes, and line-level operating response.",
            },
            {
                "name": "Echo",
                "role": "Inventory Systems Lead",
                "source": "manufacturing.inventory",
                "description": "Tracks stock posture, replenishment timing, and downstream inventory dependencies.",
            },
            {
                "name": "Omega",
                "role": "Quality Command Lead",
                "source": "manufacturing.quality",
                "description": "Owns defect-risk review, release-readiness checks, and QA coordination.",
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
            "production_plan": ("Tech", "Draft the production plan, capacity shifts, and line sequencing."),
            "throughput_ops": ("Wrecker", "Assess throughput blockers and recommend immediate operational adjustments."),
            "inventory_systems": ("Echo", "Review inventory dependencies, replenishment timing, and stock exposure."),
            "quality_command": ("Omega", "Summarize quality checkpoints, defect risk, and release readiness."),
        }
        delegated_to, default_response = routes.get(action, (self.name, "Summarize manufacturing next steps and required line actions."))

        return {
            "director": self.name,
            "delegated_to": delegated_to,
            "workstream": action,
            "instruction": instruction,
            "response": instruction or default_response,
            "next_steps": [
                "Confirm production timing and output targets.",
                "Validate inventory and quality dependencies before execution.",
                "Return capacity or readiness blockers to the Operations & Propaganda council.",
            ],
        }


manager = ManufacturingOfficeDirector()


@app.get("/health")
async def health():
    return {"status": "healthy", "office": "manufacturing", "timestamp": datetime.utcnow().isoformat()}


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

    if action == "get_production_status":
        return {"status": "success", "data": {"units_produced": 5000, "efficiency": "94%"}}
    if action == "get_inventory":
        return {"status": "success", "data": {"stock_level": 15000}}
    if action == "production_plan":
        return {"status": "success", "data": manager.automated_task_router("production_plan", request)}
    if action == "throughput_ops":
        return {"status": "success", "data": manager.automated_task_router("throughput_ops", request)}
    if action == "inventory_systems":
        return {"status": "success", "data": manager.automated_task_router("inventory_systems", request)}
    if action == "quality_command":
        return {"status": "success", "data": manager.automated_task_router("quality_command", request)}
    if action == "message":
        instruction = (request.get("instruction") or "").strip()
        lower_instruction = instruction.lower()
        delegated_action = "production_plan"
        if any(token in lower_instruction for token in ["inventory", "stock", "replenish", "warehouse"]):
            delegated_action = "inventory_systems"
        elif any(token in lower_instruction for token in ["quality", "defect", "compliance", "inspection"]):
            delegated_action = "quality_command"
        elif any(token in lower_instruction for token in ["throughput", "capacity", "line", "bottleneck", "output"]):
            delegated_action = "throughput_ops"

        routed = manager.automated_task_router(delegated_action, request)
        routed["response"] = "Acknowledged. Manufacturing will produce a plan covering capacity, inventory, and quality readiness."
        return {"status": "success", "data": routed}

    return {"status": "unknown_action"}


@app.get("/")
async def root():
    return {"service": "Manufacturing Office", "manager": manager.get_status()}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
