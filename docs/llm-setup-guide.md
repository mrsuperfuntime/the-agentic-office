# LLM Integration Setup Guide

This guide walks you through setting up the LLM integration layer for the Agentic Office system.

## Overview

The Agentic Office now features intelligent, LLM-powered autonomous agents that can:
- **Make intelligent decisions** using AI reasoning
- **Support multiple LLM providers** (Ollama, Groq)
- **Fallback gracefully** if one provider fails
- **Switch providers easily** with environment variables
- **Operate offline** with local Ollama or online with Groq

## Quick Start

### Option 1: Groq (Easiest - Cloud-Based, Fast)

**No local setup required. Instant inference.**

1. Get free Groq API key: https://console.groq.com
2. Create `.env` file:
   ```bash
   cp .env.example .env
   ```
3. Edit `.env`:
   ```bash
   LLM_PRIMARY_PROVIDER=groq
   GROQ_API_KEY=your_actual_key_from_groq_console
   LLM_FALLBACK_PROVIDER=ollama
   ```
4. Done! Services will use Groq

### Option 2: Ollama (Recommended for Development - Free, Local)

**Runs on your machine. No API keys needed.**

#### Step 1: Install Ollama
- Download from [ollama.com](https://ollama.com)
- Run installer
- Restart terminal

#### Step 2: Pull a Model
```bash
ollama pull mistral
```

(Other options: `ollama pull llama2`, `ollama pull neural-chat`)

#### Step 3: Start Ollama
```bash
ollama serve
```

Leave this running in a terminal window.

#### Step 4: Configure Environment
```bash
cp .env.example .env
```

Edit `.env`:
```bash
LLM_PRIMARY_PROVIDER=ollama
OLLAMA_URL=http://localhost:11434
OLLAMA_MODEL=mistral
GROQ_API_KEY=         # Can be empty
LLM_FALLBACK_PROVIDER=groq
```

#### Step 5: Verify Connection
```bash
curl http://localhost:11434/api/tags
```

Should return list of models.

### Option 3: Hybrid (Best for Production)

Use both providers for reliability:

```bash
cp .env.example .env
```

Edit `.env`:
```bash
# Primary: Fast cloud inference
LLM_PRIMARY_PROVIDER=groq
GROQ_API_KEY=your_actual_key_from_groq_console
GROQ_MODEL=mixtral-8x7b-32768

# Fallback: Local backup if Groq fails
LLM_FALLBACK_PROVIDER=ollama
OLLAMA_URL=http://localhost:11434
OLLAMA_MODEL=mistral

# Always use fallback
LLM_ENABLE_FALLBACK=true
```

## Installation

### Install Dependencies

All office services now require LLM packages:

```bash
# Automatically installed if using Docker
docker-compose up -d

# Or manually for local development
pip install -r requirements.txt

# Specifically:
pip install groq requests python-dotenv
```

### Docker Setup

The `docker-compose.yml` is pre-configured. Just run:

```bash
docker-compose up -d
```

Docker will:
- Install all dependencies
- Load `.env` configuration
- Start all offices with LLM support

## Testing the LLM Integration

### Test Ollama Directly

```bash
curl -X POST http://localhost:11434/api/chat \
  -H "Content-Type: application/json" \
  -d '{
    "model": "mistral",
    "messages": [{"role": "user", "content": "What is AI?"}],
    "stream": false
  }'
```

### Test via Office API

```bash
# Sales Office - Analyze Prospect
curl -X POST http://localhost:8001/analyze-prospect \
  -H "Content-Type: application/json" \
  -d '{
    "prospect_data": "[{\"name\": \"Acme Inc\", \"revenue\": \"$10M\"}]"
  }'

# Finance Office - Analyze Budget
curl -X POST http://localhost:8005/analyze-budget \
  -H "Content-Type: application/json" \
  -d '{
    "request_details": "Request for $500k for marketing",
    "budget_info": "Annual budget: $5M"
  }'

# Social Media Office - Create Content
curl -X POST http://localhost:8007/create-content \
  -H "Content-Type: application/json" \
  -d '{
    "platform": "twitter",
    "topic": "New AI features launch",
    "tone": "excited"
  }'
```

### Check Provider Status

```bash
# Any office endpoint
curl http://localhost:8001/manager | jq '.llm_status'

# Output:
# {
#   "primary": "ollama",
#   "fallback": "groq",
#   "available_providers": ["ollama"]
# }
```

## Configuration Reference

### Environment Variables

**Provider Selection**
```bash
LLM_PRIMARY_PROVIDER=ollama      # groq or ollama
LLM_FALLBACK_PROVIDER=groq       # groq or ollama
LLM_ENABLE_FALLBACK=true         # Enable automatic fallback
```

**Ollama Settings**
```bash
OLLAMA_URL=http://localhost:11434    # Ollama server URL
OLLAMA_MODEL=mistral                 # Model to use: mistral, llama2, neural-chat, etc.
```

**Groq Settings**
```bash
GROQ_API_KEY=your_key_here          # Get from console.groq.com
GROQ_MODEL=mixtral-8x7b-32768       # Fast model, good for most use cases
```

**Generation Settings**
```bash
LLM_TEMPERATURE=0.7                 # 0.0=consistent, 1.0=creative
LLM_MAX_TOKENS=500                  # Max response length
LLM_TIMEOUT=30                      # Request timeout in seconds
```

## Troubleshooting

### "Failed to initialize Ollama"

**Problem**: `Error: Failed to initialize Ollama`

**Solution**:
1. Check Ollama is running:
   ```bash
   ollama serve
   ```
2. Check URL in `.env`:
   ```bash
   OLLAMA_URL=http://localhost:11434
   ```
3. Test connection:
   ```bash
   curl http://localhost:11434/api/tags
   ```

### "Groq API key not configured"

**Problem**: `Error: Groq API key not configured`

**Solution**:
1. Get free key: https://console.groq.com
2. Add to `.env`:
   ```bash
   GROQ_API_KEY=your_actual_key
   ```
3. Restart services

### "All LLM providers failed"

**Problem**: Neither Ollama nor Groq is working

**Solution**:
1. Check at least one provider is configured
2. Verify network connectivity
3. Check logs:
   ```bash
   docker-compose logs sales-office
   ```
4. Try manual test:
   ```bash
   # For Ollama
   curl http://localhost:11434/api/tags
   
   # For Groq
   curl https://api.groq.com/v1/models -H "Authorization: Bearer YOUR_KEY"
   ```

### Slow Responses

**Problem**: LLM requests taking 5+ seconds

**Solution**:
1. If using Ollama on CPU, enable GPU:
   - NVIDIA: Ollama auto-detects CUDA
   - Mac: Auto-detects Metal
   - Windows: Check GPU drivers

2. Try smaller model:
   ```bash
   OLLAMA_MODEL=neural-chat  # Faster than mistral
   ```

3. Use Groq for speed:
   ```bash
   LLM_PRIMARY_PROVIDER=groq
   ```

## Office-Specific Usage

Each office has LLM-powered endpoints:

### Sales Office
- `POST /analyze-prospect` - Score and rank prospects
- `POST /forecast-revenue` - Revenue forecasting
- `POST /analyze-deal` - Deal analysis

### HR Office
- `POST /evaluate-candidate` - Candidate screening
- `POST /employee-performance` - Performance decisions
- `POST /create-policy` - HR policy creation

### Finance Office
- `POST /analyze-budget` - Budget request analysis
- `POST /financial-health` - Financial assessment
- `POST /analyze-expenses` - Expense optimization

### Social Media Office
- `POST /create-content` - AI content generation
- `POST /content-strategy` - Strategy planning
- `POST /analyze-trends` - Trend analysis

### Customer Service Office
- `POST /route-ticket` - Intelligent routing
- `POST /respond-to-complaint` - Response generation

### Procurement Office
- `POST /evaluate-vendors` - Vendor scoring
- `POST /negotiate-pricing` - Pricing analysis

### Manufacturing Office
- `POST /production-schedule` - Schedule planning
- `POST /optimize-inventory` - Inventory management

## Example: Building an Intelligent Workflow

```python
from shared.libs import get_llm_client, generate_office_decision

# Get client
llm_client = get_llm_client()

# Sales analyzes prospects
prospect_analysis = generate_office_decision(
    office_type="sales",
    decision_type="prospect_scoring",
    llm_client=llm_client,
    prospects="[{'name': 'Acme Inc', 'revenue': '$10M', 'industry': 'Tech'}]"
)

# Finance reviews budget for top prospect
budget_decision = generate_office_decision(
    office_type="finance",
    decision_type="budget_analysis",
    llm_client=llm_client,
    request_details="Allocate $50k for Acme Inc deal",
    budget_info="Marketing budget: $200k"
)

# Social Media creates announcement
content = generate_office_decision(
    office_type="social-media",
    decision_type="create_content",
    llm_client=llm_client,
    platform="LinkedIn",
    topic="Partnership with Acme Inc",
    tone="professional"
)

print(f"Prospect Score: {prospect_analysis}")
print(f"Budget Approved: {budget_decision}")
print(f"Social Post: {content}")
```

## Performance Benchmarks

### Ollama (Mistral 7B on CPU)
- First request: 5-15 seconds (model loading)
- Subsequent requests: 2-5 seconds
- Memory usage: 8GB

### Ollama (Mistral 7B on GPU)
- First request: 1-3 seconds
- Subsequent requests: 0.5-1.5 seconds
- Memory usage: 8GB VRAM

### Groq (Mixtral 8x7B)
- Any request: 0.2-0.8 seconds
- Memory usage: None (cloud)
- Cost: Free tier (5000 requests/day), then ~$0.0005 per request

## Next Steps

1. **Choose a provider** (Ollama recommended for dev, Groq for prod)
2. **Configure `.env`** with your settings
3. **Start services**: `docker-compose up -d`
4. **Test an office**: `curl http://localhost:8001/manager`
5. **Try an AI endpoint**: See examples above
6. **Monitor logs**: `docker-compose logs -f`

## Support

For issues:
1. Check troubleshooting section above
2. Review logs: `docker-compose logs <service-name>`
3. Verify `.env` configuration
4. Test provider directly (curl commands above)
5. Check internet connection for cloud providers

## Resources

- [Ollama Documentation](https://ollama.ai)
- [Groq Console](https://console.groq.com)
- [Shared Libraries README](../shared/libs/README.md)
- [LLM Provider Code](../shared/libs/llm_provider.py)
- [Office Prompts](../shared/libs/prompts.py)
