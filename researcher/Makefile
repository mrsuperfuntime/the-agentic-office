PROJECT_DIR := $(shell pwd)
VENV        := $(PROJECT_DIR)/venv
PYTHON      := $(VENV)/bin/python
UVICORN     := $(VENV)/bin/uvicorn
SERVICE     := researcher

.DEFAULT_GOAL := help

# Read .env values if the file exists
-include .env
HOST ?= 127.0.0.1
PORT ?= 8009

.PHONY: help install start stop restart logs status pull-model docker-up docker-down clean

help:
	@echo ""
	@echo "  THE RESEARCHER — available commands"
	@echo ""
	@echo "  make install       Full Linux setup (venv, deps, Ollama check, systemd)"
	@echo "  make start         Start via systemd"
	@echo "  make stop          Stop the systemd service"
	@echo "  make restart       Restart the systemd service"
	@echo "  make logs          Follow live service logs"
	@echo "  make status        Show service status + health check"
	@echo "  make run           Run directly in terminal (no systemd)"
	@echo "  make pull-model    Pull the recommended Ollama model (qwen2.5:7b)"
	@echo "  make docker-up     Start via Docker Compose (with Ollama)"
	@echo "  make docker-down   Stop Docker Compose stack"
	@echo "  make clean         Remove venv and __pycache__"
	@echo ""

install:
	bash scripts/install.sh

run:
	@[[ -f $(VENV)/bin/activate ]] || (echo "Run 'make install' first"; exit 1)
	@source $(VENV)/bin/activate && \
		cd $(PROJECT_DIR) && \
		$(UVICORN) main:app --host $(HOST) --port $(PORT)

start:
	sudo systemctl start $(SERVICE)
	@echo "Started — http://$(HOST):$(PORT)/ui"

stop:
	sudo systemctl stop $(SERVICE)

restart:
	sudo systemctl restart $(SERVICE)

logs:
	journalctl -u $(SERVICE) -f --output=short-precise

status:
	@echo "=== Systemd status ==="
	@systemctl status $(SERVICE) --no-pager || true
	@echo ""
	@echo "=== Health check ==="
	@curl -sf http://$(HOST):$(PORT)/health | python3 -m json.tool || echo "Service not responding"

pull-model:
	ollama pull qwen2.5:7b

docker-up:
	docker compose up -d --build
	@echo "Started — http://127.0.0.1:$(PORT)/ui"

docker-down:
	docker compose down

clean:
	rm -rf venv __pycache__ **/__pycache__
