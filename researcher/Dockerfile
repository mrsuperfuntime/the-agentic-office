FROM python:3.11-slim

# Non-root user for runtime security
RUN useradd -m -u 1000 researcher

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY main.py research_agent.py tools.py ./
COPY static/ ./static/

USER researcher

EXPOSE 8009

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8009"]
