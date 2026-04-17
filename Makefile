COMPOSE=docker compose

.PHONY: up down rebuild logs ps test api db-migrate health benchmark benchmark-domains

up:
	$(COMPOSE) up -d --build

down:
	$(COMPOSE) down

rebuild:
	$(COMPOSE) build --no-cache api
	$(COMPOSE) up -d

logs:
	$(COMPOSE) logs -f --tail=200

ps:
	$(COMPOSE) ps

test:
	python3 -m pytest -q

api:
	uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload

db-migrate:
	alembic upgrade head

health:
	curl http://127.0.0.1:8080/health

benchmark:
	python3 scripts/benchmark_api.py --url http://127.0.0.1:8080/generate --requests 20 --warmup 3 --out docs/results/benchmark-generate.json

benchmark-domains:
	python3 scripts/benchmark_api.py --url http://127.0.0.1:8080/generate/domains --requests 20 --warmup 3 --out docs/results/benchmark-domains.json
