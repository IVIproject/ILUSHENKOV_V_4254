# ai-servise

Local API service for text generation using FastAPI + Ollama + PostgreSQL.

## Project readiness level

The service already includes:

- API layer (FastAPI) with OpenAPI docs
- local LLM integration via Ollama
- PostgreSQL logging of requests/responses
- streaming generation endpoint
- migration support via Alembic
- Docker stack (api + postgres + nginx)
- tests for core endpoints

## Prerequisites

- Docker + Docker Compose
- Running Ollama server with a downloaded model (local or remote)

## Quick start (Docker: API + Postgres + Nginx)

1. Prepare environment file:

```bash
cp .env.example .env
```

2. Start stack:

```bash
docker compose up -d --build
```

3. Check containers:

```bash
docker compose ps
```

API is available through Nginx at:

- `http://127.0.0.1:8080`
- Swagger: `http://127.0.0.1:8080/docs`

## API checks

- Health check:

```bash
curl http://127.0.0.1:8080/health
```

- Generic text generation:

```bash
curl -X POST "http://127.0.0.1:8080/generate" \
  -H "Content-Type: application/json" \
  -d '{"prompt":"Suggest 3 domain names for an IT service"}'
```

- Domain names generation (business endpoint):

```bash
curl -X POST "http://127.0.0.1:8080/generate/domains" \
  -H "Content-Type: application/json" \
  -d '{"business_context":"cloud hosting and VPS","keywords":["cloud","vps"],"zone":".ru","count":7}'
```

- Stream generation (NDJSON):

```bash
curl -N -X POST "http://127.0.0.1:8080/generate/stream" \
  -H "Content-Type: application/json" \
  -d '{"prompt":"Write a short greeting"}'
```

- Request history:

```bash
curl "http://127.0.0.1:8080/history?limit=5"
```

- Service usage stats:

```bash
curl "http://127.0.0.1:8080/stats"
```

## Migrations (Alembic)

From local virtual environment:

```bash
alembic upgrade head
```

Create new migration:

```bash
alembic revision -m "describe_change"
```

## Makefile shortcuts

```bash
make up
make ps
make test
make logs
make down
```

## Optional ML dependencies

The API does not require `torch` / `transformers` for basic Ollama proxy mode.
If you want local model experimentation with Hugging Face stack, install separately:

```bash
pip install -r requirements-ml.txt
```

## Local development (without API container)

If you want to run only PostgreSQL in Docker and run API from venv:

```bash
docker compose up -d postgres
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

## Documentation for report and defense

- architecture description: `docs/architecture.md`
- demonstration script: `docs/defense-scenario.md`
- experiment methodology: `docs/experiment-methodology.md`

## Experimental part (for report)

Run quick API benchmark and save measurable metrics:

```bash
make benchmark
```

This command creates JSON report:

- `docs/results/benchmark-generate.json`

You can include these values directly into report tables (latency avg/p95/p99, status code distribution, payload size).

Example for domain generation scenario:

```bash
python3 scripts/benchmark_api.py \
  --url http://127.0.0.1:8080/generate/domains \
  --requests 20 \
  --warmup 3 \
  --out docs/results/benchmark-domains.json
```
