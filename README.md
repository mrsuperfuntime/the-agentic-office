# The Agentic Office

A microservices-based virtual office system where AI agents autonomously manage different business functions with agentic separation, office managers, and structured teams.

## Architecture

The system is built on a microservices architecture with:
- **Office Orchestrator**: Central management service for inter-office communication
- **Sales Office**: Handles customer acquisition and deal management
- **HR Office**: Manages recruitment, employee records, and payroll
- **Customer Service Office**: Manages customer support and issue resolution
- **Procurement Office**: Handles vendor management and purchasing
- **Finance Office**: Manages budgeting, reporting, and financial analysis
- **Manufacturing Office**: Handles production planning and execution

## Project Structure

```
The Agentic Office/
├── services/
│   ├── office-orchestrator/     # Central orchestration service
│   ├── sales-office/             # Sales department microservice
│   ├── hr-office/                # HR department microservice
│   ├── customer-service-office/  # Customer service microservice
│   ├── procurement-office/       # Procurement microservice
│   ├── finance-office/           # Finance microservice
│   └── manufacturing-office/     # Manufacturing microservice
├── shared/
│   ├── libs/                     # Shared libraries and utilities
│   └── models/                   # Shared data models
├── docs/                         # Documentation
└── docker-compose.yml            # Multi-service orchestration
```

## Each Office Contains

- **Office Manager Agent**: Autonomous agent that manages the office
- **Team Agents**: Specialized agents for different departments within the office
- **Service Layer**: Business logic implementation
- **API Endpoints**: REST/gRPC interfaces for inter-office communication
- **Database**: Office-specific persistent storage

## Technology Stack

- **Backend**: Python (FastAPI/Flask) + Node.js
- **Messaging**: Message queues for inter-office communication
- **Database**: PostgreSQL / MongoDB (per office)
- **Orchestration**: Docker Compose / Kubernetes-ready
- **Agents**: LLM-based autonomous agents

## Getting Started

### Prerequisites
- Docker & Docker Compose
- Python 3.9+
- Node.js 18+
- PostgreSQL 14+

### Installation

1. Clone the repository
2. Install dependencies:
   ```bash
   pip install -r requirements.txt
   npm install
   ```

3. Set up environment variables:
   ```bash
   cp .env.example .env
   ```

   Then replace placeholder secret values in `.env` before running the stack.

4. Run all services:
   ```bash
   docker-compose up -d
   ```

## Free Local LLM Profile (Strict Ollama)

Use this path to run fully local LLM inference with fail-fast checks and no cloud fallback:

1. Pull local model:
   ```bash
   ollama pull mistral
   ```

2. Start one-command local stack:
   ```bash
   powershell -ExecutionPolicy Bypass -File .\scripts\run-local-office-stack.ps1 -Office finance -OllamaModel mistral
   ```

3. Verify generated response is non-empty:
   ```bash
   $headers = @{ 'X-API-Key' = 'agentic-office-dev-key' }
   $body = @{ from_office='user'; to_office='finance'; instruction='Summarize Q2 budget risk in 3 bullet points.' } | ConvertTo-Json
   Invoke-RestMethod -Uri "http://127.0.0.1:8000/message" -Method Post -Headers $headers -ContentType "application/json" -Body $body
   ```

If Ollama is unreachable or the model is missing, offices now fail fast at startup with a clear error message.

## Office Descriptions

### Sales Office
Manages customer acquisition, deal tracking, pipeline management, and sales forecasting.

### HR Office
Handles recruitment, employee management, benefits, payroll, and organizational development.

### Customer Service Office
Manages customer inquiries, issue resolution, satisfaction tracking, and feedback.

### Procurement Office
Handles vendor relationships, purchase orders, supply chain, and cost management.

### Finance Office
Manages budgeting, financial reporting, analysis, and organizational fiscal strategy.

### Manufacturing Office
Handles production scheduling, quality assurance, inventory, and operational efficiency.

### Social Media Office
Creates post drafts and stores campaign artifacts (posts, metadata, and image briefs) in an output folder.

### IT Office
Manages platform integrations (X, Instagram, LinkedIn, TikTok, Facebook) and records publish connector events.

## Data Output Folders

Artifact output can be designated by environment variables:

- `SOCIAL_MEDIA_OUTPUT_ROOT` for social-media campaign artifacts
- `IT_OUTPUT_ROOT` for IT integration and publish logs

With Docker Compose these are mapped to `./data-output` so generated files are available on the host.

## Development

Each office service is independent and can be developed, tested, and deployed separately.

See individual service READMEs for specific setup instructions.

## API Communication

Offices communicate via:
- REST APIs for synchronous operations
- Message queues for asynchronous operations
- Shared event bus for office-wide events
