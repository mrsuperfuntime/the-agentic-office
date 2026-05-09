# Shared Libraries - LLM Integration

This directory contains shared libraries for the Agentic Office system, including LLM provider abstraction and office-specific prompts.

## Components

### 1. LLM Provider (`llm_provider.py`)

Universal LLM client with support for multiple providers and automatic fallback.

**Supported Providers:**
- **Ollama** - Local LLM inference
- **Groq** - Fast cloud-based LLM API

**Features:**
- Automatic fallback to secondary provider
- Provider abstraction for easy switching
- Built-in error handling and logging
- Configurable temperature, tokens, and timeout

**Usage:**

```python
from shared.libs import get_llm_client

# Get global client (automatically configured)
client = get_llm_client()

# Generate response
response = client.generate(
    prompt="What is 2 + 2?",
    system="You are a helpful math tutor."
)

# Check provider status
status = client.get_status()
print(status)  # {'primary': 'ollama', 'fallback': 'groq', 'available_providers': [...]}
```

**Configuration via Environment Variables:**

```bash
# Provider selection
LLM_PRIMARY_PROVIDER=ollama          # or groq
LLM_FALLBACK_PROVIDER=groq           # or ollama
LLM_ENABLE_FALLBACK=true

# Ollama settings
OLLAMA_URL=http://localhost:11434
OLLAMA_MODEL=mistral

# Groq settings
GROQ_API_KEY=your_key_here
GROQ_MODEL=mixtral-8x7b-32768

# Generation settings
LLM_TEMPERATURE=0.7
LLM_MAX_TOKENS=500
LLM_TIMEOUT=30
```

### 2. Office-Specific Prompts (`prompts.py`)

Centralized prompt management for each office type with specialized decision-making templates.

**Supported Offices:**
- Sales Office
- HR Office
- Customer Service Office
- Procurement Office
- Finance Office
- Manufacturing Office
- Social Media Office

**Features:**
- System prompts for each office role
- Decision-specific prompt templates
- Consistent voice and behavior per office
- Easy extensibility for new decision types

**Usage:**

```python
from shared.libs import OfficePromptsFactory, generate_office_decision, get_llm_client

# Get system prompt for an office
system_prompt = OfficePromptsFactory.get_system_prompt("sales")

# Get a specific decision prompt
user_prompt = OfficePromptsFactory.get_decision_prompt(
    "sales",
    "prospect_scoring",
    prospects="[{'name': 'Acme Inc', 'revenue': '$10M'}, ...]"
)

# Generate a decision
llm_client = get_llm_client()
response = generate_office_decision(
    office_type="sales",
    decision_type="prospect_scoring",
    llm_client=llm_client,
    prospects="[{'name': 'Acme Inc', 'revenue': '$10M'}, ...]"
)
```

**Available Decision Types by Office:**

**Sales Office:**
- `analyze_deal` - Evaluate sales opportunities
- `forecast_revenue` - Revenue forecasting
- `prospect_scoring` - Rank and prioritize prospects
- `strategy_recommendation` - Sales strategy planning

**HR Office:**
- `candidate_evaluation` - Evaluate job candidates
- `employee_performance` - Performance management decisions
- `payroll_decision` - Payroll and compensation decisions
- `policy_recommendation` - HR policy creation

**Customer Service Office:**
- `ticket_routing` - Route support tickets
- `complaint_response` - Generate complaint responses
- `satisfaction_analysis` - Analyze customer satisfaction
- `escalation_decision` - Determine escalation path

**Procurement Office:**
- `vendor_evaluation` - Evaluate and select vendors
- `price_negotiation` - Negotiate pricing
- `po_review` - Review purchase orders
- `supply_chain` - Optimize supply chain

**Finance Office:**
- `budget_analysis` - Analyze budget requests
- `financial_health` - Assess financial performance
- `expense_review` - Review and optimize expenses
- `investment_decision` - Investment decision making

**Manufacturing Office:**
- `production_schedule` - Production planning
- `quality_issue` - Quality issue resolution
- `inventory_optimization` - Inventory management
- `efficiency_improvement` - Process optimization

**Social Media Office:**
- `create_content` - Create social media content
- `content_strategy` - Plan content strategy
- `trending_analysis` - Analyze trends
- `engagement_boost` - Boost engagement

## Setup

### 1. Install Dependencies

```bash
# For Ollama support
pip install requests

# For Groq support
pip install groq

# For all features
pip install requests groq
```

### 2. Configure Environment

Create a `.env` file in the project root:

```bash
cp .env.example .env
```

Edit `.env` with your settings:

```bash
LLM_PRIMARY_PROVIDER=ollama
OLLAMA_URL=http://localhost:11434
OLLAMA_MODEL=mistral
GROQ_API_KEY=your_key_here
```

### 3. Start Ollama (Optional)

```bash
# Install Ollama from ollama.com, then:
ollama pull mistral
ollama serve
```

## Integration with Office Services

Each office service should import and use the LLM client:

```python
from fastapi import FastAPI
from shared.libs import get_llm_client, generate_office_decision

app = FastAPI()
llm_client = get_llm_client()

@app.post("/make-decision")
async def make_decision(request: dict):
    office_type = request.get("office")  # e.g., "sales"
    decision_type = request.get("decision_type")  # e.g., "prospect_scoring"
    
    response = generate_office_decision(
        office_type=office_type,
        decision_type=decision_type,
        llm_client=llm_client,
        **request.get("params", {})
    )
    
    return {"response": response}
```

## Extending the System

### Add a New Office Prompt Class

```python
# In prompts.py
class NewOfficePrompts:
    SYSTEM_PROMPT = "You are the New Office Manager..."
    
    DECISION_TYPE = "Prompt template for decision"

# Register in PROMPTS_MAP
OfficePromptsFactory.PROMPTS_MAP["new-office"] = NewOfficePrompts
```

### Add a New LLM Provider

```python
# In llm_provider.py
class NewProvider:
    def __init__(self, config: LLMConfig):
        self.config = config
    
    def generate(self, prompt: str, system: Optional[str] = None) -> Optional[str]:
        # Implementation
        pass

# Add to LLMClient._initialize_providers()
```

## Troubleshooting

### Ollama Connection Error
```
Error: Failed to initialize Ollama
```
**Solution:** Ensure Ollama is running: `ollama serve`

### Groq API Error
```
Error: Groq API key not configured
```
**Solution:** Set `GROQ_API_KEY` environment variable

### All Providers Failed
```
Error: All LLM providers failed
```
**Solution:** Check logs and ensure at least one provider is properly configured

## Performance Tips

- **Use Groq for production** - Faster responses, reliable
- **Use Ollama for development** - Free, runs locally
- **Enable fallback** - Always have a backup provider
- **Adjust temperature** - Lower (0.3) for consistent decisions, higher (0.9) for creativity
- **Set appropriate timeout** - Balance speed vs reliability

## API Documentation

See individual module docstrings for complete API documentation.

```python
from shared.libs import LLMClient, OfficePromptsFactory

help(LLMClient)
help(OfficePromptsFactory)
```
