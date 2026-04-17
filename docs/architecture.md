# ai-servise Architecture

## High-level components

1. **Nginx (reverse proxy)**  
   Accepts HTTP requests on host port `8080` and forwards them to API service.

2. **FastAPI service (`app.main`)**  
   Core application logic:
   - health checks (`/health`)
   - text generation (`/generate`)
   - stream generation (`/generate/stream`)
   - domain name generation (`/generate/domains`)
   - request history (`/history`)
   - operational statistics (`/stats`)

3. **PostgreSQL**  
   Stores prompts, generated answers, and generation metadata in table `request_logs`.

4. **Ollama (external/local model runtime)**  
   API service calls Ollama using `OLLAMA_HOST` and `OLLAMA_MODEL`.

## Request flow

1. Client sends request to `http://localhost:8080/...`
2. Nginx proxies request to FastAPI container (`api:8000`)
3. FastAPI validates input via Pydantic schemas
4. FastAPI calls Ollama chat API
5. FastAPI stores prompt/answer into PostgreSQL
6. FastAPI returns response to client (JSON or NDJSON stream)

## Logging and traceability

- Middleware generates/propagates `X-Request-ID`
- Request ID is returned in response headers
- Application logs include request ID for troubleshooting

## Deployment options

- **Docker mode (recommended)**: `postgres + api + nginx` in one compose stack
- **Local dev mode**: API from venv, PostgreSQL in Docker

