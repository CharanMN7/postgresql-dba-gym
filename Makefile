# PostgreSQL DBA Gym — developer Makefile.
#
# All targets run through `docker compose` so you don't need Postgres
# or Python installed on the host. Run `make help` for the target list.

SHELL := /bin/bash
COMPOSE ?= docker compose
SERVICE ?= server
HOST_URL ?= http://localhost:8000

.DEFAULT_GOAL := help

.PHONY: help check-env build up down restart logs shell demo inference smoke validate clean

help: ## Show this help
	@awk 'BEGIN {FS = ":.*?## "} /^[a-zA-Z_-]+:.*?## / {printf "  \033[36m%-12s\033[0m %s\n", $$1, $$2}' $(MAKEFILE_LIST)

check-env: ## Verify .env exists
	@test -f .env || { \
	  echo "ERROR: .env not found."; \
	  echo "Run: cp .env.example .env and edit it (set HF_TOKEN to your OpenAI API key)"; \
	  exit 1; \
	}

build: ## Build the Docker image
	$(COMPOSE) build

up: check-env ## Start the server detached and wait for healthy
	$(COMPOSE) up -d
	@echo "Waiting for $(SERVICE) to become healthy..."
	@for i in $$(seq 1 60); do \
	  status=$$(docker inspect -f '{{.State.Health.Status}}' pg-dba-gym 2>/dev/null || echo "starting"); \
	  if [ "$$status" = "healthy" ]; then echo "Healthy."; exit 0; fi; \
	  sleep 2; \
	done; \
	echo "Timed out waiting for health. Check: make logs"; exit 1

down: ## Stop and remove the container
	$(COMPOSE) down

restart: down up ## Restart the server

logs: ## Follow server logs
	$(COMPOSE) logs -f $(SERVICE)

shell: ## Open a bash shell inside the container
	$(COMPOSE) exec $(SERVICE) bash

demo: ## Run the scripted demo inside the container
	$(COMPOSE) exec $(SERVICE) python demo.py

inference: ## Run the OpenAI baseline agent inside the container
	$(COMPOSE) exec $(SERVICE) python inference.py

smoke: ## Run host-side curl smoke test against localhost:8000
	@HOST_URL=$(HOST_URL) bash scripts/smoke_test.sh

validate: ## Run `openenv validate` inside the container
	$(COMPOSE) exec $(SERVICE) openenv validate

clean: ## Stop, remove volumes, and prune dangling images
	$(COMPOSE) down -v
	-docker image prune -f
