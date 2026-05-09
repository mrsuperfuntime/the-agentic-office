# Getting Started

## Quick Start

### Option 1: Docker Compose (Recommended)

```bash
docker-compose up -d
```

This will start all services:
- Office Orchestrator: http://localhost:8000
- Sales Office: http://localhost:8001
- HR Office: http://localhost:8002
- Customer Service Office: http://localhost:8003
- Procurement Office: http://localhost:8004
- Finance Office: http://localhost:8005
- Manufacturing Office: http://localhost:8006

### Option 2: Local Development

Run each service separately:

```bash
# Terminal 1 - Office Orchestrator
cd services/office-orchestrator
pip install -r requirements.txt
python main.py

# Terminal 2 - Sales Office
cd services/sales-office
pip install -r requirements.txt
python main.py

# ... and so on for other offices
```

## API Testing

Get office statuses:
```bash
curl http://localhost:8000/offices
```

Submit a cross-office request:
```bash
curl -X POST http://localhost:8000/request \
  -H "Content-Type: application/json" \
  -d '{
    "from_office": "sales",
    "to_office": "finance",
    "action": "get_budget"
  }'
```

## Architecture

Each office is an autonomous microservice with:
- **Office Manager Agent**: LLM-based manager making decisions
- **Team Agents**: Specialized agents for departments
- **REST API**: For inter-office communication
- **Database**: Persistent storage for office data
- **Event Bus**: For broadcasting office-wide events

## Next Steps

1. Implement LLM agents for each office manager
2. Add persistent storage (PostgreSQL)
3. Implement message queue for async operations
4. Create admin dashboard
5. Add authentication and authorization
