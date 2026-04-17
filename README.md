# ai-servise

Local API service for text generation using FastAPI + Ollama + PostgreSQL.

## Prerequisites

- Python 3.10+
- Docker + Docker Compose
- Running Ollama server with a downloaded model

## Quick start

1. Start PostgreSQL:

```bash
docker compose up -d
```

2. Prepare environment file:

```bash
cp .env.example .env
```

3. Create and activate virtual environment:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

4. Run API:

```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

## API checks

- Health check:

```bash
curl http://127.0.0.1:8000/health
```

- Generate text:

```bash
curl -X POST "http://127.0.0.1:8000/generate" \
  -H "Content-Type: application/json" \
  -d '{"prompt":"Suggest 3 domain names for an IT service"}'
```

- Stream generation (NDJSON):

```bash
curl -N -X POST "http://127.0.0.1:8000/generate/stream" \
  -H "Content-Type: application/json" \
  -d '{"prompt":"Write a short greeting"}'
```

- Request history:

```bash
curl "http://127.0.0.1:8000/history?limit=5"
```

## Migrations (Alembic)

- Apply migrations:

```bash
alembic upgrade head
```

- Create new migration:

```bash
alembic revision -m "describe_change"
```
