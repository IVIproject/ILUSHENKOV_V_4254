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

## OpenRouter-like gateway (MVP)

New gateway capabilities:

- user registration and API key issuance
- model catalog with local and external provider routing
- pay-per-token balance accounting
- external proxy to OpenAI-compatible upstream (for example ChatGPT)
- simple web page for pricing and quick onboarding (`GET /gateway`)

### Gateway setup

Add variables to `.env`:

```env
OLLAMA_MODEL=qwen2.5:3b
OLLAMA_SECONDARY_MODEL=llama3.2:3b
OPENAI_BASE_URL=https://api.openai.com/v1/chat/completions
OPENAI_API_KEY=
```

Notes:

- `OLLAMA_MODEL` and `OLLAMA_SECONDARY_MODEL` are local Ollama models.
- if `OPENAI_API_KEY` is empty, proxy model calls return provider error.
- `OPENAI_BASE_URL` must point to full chat-completions URL.

### Register user and get API key

```bash
curl -X POST "http://127.0.0.1:8080/gateway/register" \
  -H "Content-Type: application/json" \
  -d '{"email":"user@example.com","password":"strong-pass-123","tariff_code":"starter"}'
```

Top up test balance:

```bash
curl -X POST "http://127.0.0.1:8080/gateway/tokens/topup" \
  -H "Content-Type: application/json" \
  -H "X-Gateway-Key: asv_your_key_here" \
  -d '{"tokens":100000}'
```

List models:

```bash
curl -X GET "http://127.0.0.1:8080/gateway/models" \
  -H "X-Gateway-Key: asv_your_key_here"
```

### Gateway inference

Local model:

```bash
curl -X POST "http://127.0.0.1:8080/gateway/generate" \
  -H "Content-Type: application/json" \
  -H "X-Gateway-Key: asv_your_key_here" \
  -d '{"model_id":"local/qwen2.5-3b","prompt":"Привет, коротко расскажи про VPS"}'
```

Proxy model (OpenAI upstream):

```bash
curl -X POST "http://127.0.0.1:8080/gateway/generate" \
  -H "Content-Type: application/json" \
  -H "X-Gateway-Key: asv_your_key_here" \
  -d '{"model_id":"proxy/openai-gpt-4o-mini","prompt":"Сделай краткий план запуска сайта"}'
```

Billing is token-based:

- request is accepted only if user has enough balance
- `tokens_spent` is deducted from account
- usage transaction is saved in `gateway_usage_logs`

## 3 working modes (single endpoint)

Unified endpoint:

```bash
POST /mode/run
```

Supported modes:

1. `chat` - standard assistant response
2. `domains` - domain list generation without numbering/comments
3. `support_faq` - support response using imported FAQ history

Mode examples:

```bash
# 1) chat
curl -X POST "http://127.0.0.1:8080/mode/run" \
  -H "Content-Type: application/json" \
  -d '{"mode":"chat","payload":{"prompt":"Коротко опиши услугу VPS-хостинга"}}'

# 2) domains
curl -X POST "http://127.0.0.1:8080/mode/run" \
  -H "Content-Type: application/json" \
  -d '{"mode":"domains","payload":{"business_context":"регистрация доменов и хостинг","keywords":["domain","cloud"],"zone":".ru","count":5}}'

# 3) support_faq
curl -X POST "http://127.0.0.1:8080/mode/run" \
  -H "Content-Type: application/json" \
  -d '{"mode":"support_faq","payload":{"question":"Как продлить домен?","max_context_items":5}}'
```

### PHP page generation (file output only)

`php_page` mode is intentionally disabled in `/mode/run`.
Use the dedicated endpoint below to generate and download a `.php` file from a named template:

```bash
curl -X POST "http://127.0.0.1:8080/page-template/generate-file" \
  -H "Content-Type: application/json" \
  -d '{"template_name":"hosting.php","content_prompt":"Сделай продающий текст страницы хостинга","output_filename":"hosting-generated.php"}' \
  --output hosting-generated.php
```

### FAQ import examples

If `ADMIN_API_KEY` is configured in `.env`, include the header `X-API-Key`.

```bash
# structured FAQ import
curl -X POST "http://127.0.0.1:8080/support/faq/import" \
  -H "Content-Type: application/json" \
  -H "X-API-Key: your-admin-key" \
  -d '{"items":[{"question":"Как продлить домен?","answer":"Продление доступно в личном кабинете.","source":"support_chat"}]}'

# import from support transcript text
curl -X POST "http://127.0.0.1:8080/support/dialogs/import" \
  -H "Content-Type: application/json" \
  -H "X-API-Key: your-admin-key" \
  -d '{"transcript":"Q: Как продлить домен?\nA: Через личный кабинет."}'
```

### How `ADMIN_API_KEY` works (simple)

`ADMIN_API_KEY` protects only admin-like import endpoints:

- `POST /support/faq/import`
- `POST /support/dialogs/import`

If `ADMIN_API_KEY` is empty in `.env`, these endpoints work **without** a key.

If `ADMIN_API_KEY` is set, each import request must include:

```http
X-API-Key: <your key from .env>
```

Quick setup:

1. Open `.env` and set:

```env
ADMIN_API_KEY=my-secret-key-123
```

2. Restart API:

```bash
docker compose up -d --build
```

3. Use key in request:

```bash
curl -X POST "http://127.0.0.1:8080/support/faq/import" \
  -H "Content-Type: application/json" \
  -H "X-API-Key: my-secret-key-123" \
  -d '{"items":[{"question":"Как продлить домен?","answer":"Через личный кабинет.","source":"support_chat"}]}'
```

Without key (or with wrong key) API returns `401`.

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

`/stats` now also includes FAQ quality metrics:

- `support_faq_total_requests` - number of support FAQ requests evaluated
- `support_faq_zero_match_total` - count of requests with zero overlap to FAQ context
- `support_faq_no_match_rate` - share of requests with zero overlap to FAQ context
- `support_faq_avg_relevance_score` - average overlap score (higher is better)
- `support_faq_top_questions` - most frequent normalized support questions

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
