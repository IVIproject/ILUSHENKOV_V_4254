# ai-servise

Local API service for text generation using FastAPI + Ollama + PostgreSQL.

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

- `http://127.0.0.1`
- Swagger: `http://127.0.0.1/docs`

## API checks

- Health check:

```bash
curl http://127.0.0.1/health
```

- Generate text:

```bash
curl -X POST "http://127.0.0.1/generate" \
  -H "Content-Type: application/json" \
  -d '{"prompt":"Suggest 3 domain names for an IT service"}'
```

- Stream generation (NDJSON):

```bash
curl -N -X POST "http://127.0.0.1/generate/stream" \
  -H "Content-Type: application/json" \
  -d '{"prompt":"Write a short greeting"}'
```

- Request history:

```bash
curl "http://127.0.0.1/history?limit=5"
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
