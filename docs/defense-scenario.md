# Defense demo scenario

## Goal
Show a complete request lifecycle in `ai-servise`:

1. receive API request,
2. send prompt to local Ollama model,
3. return generated result,
4. persist interaction in PostgreSQL,
5. inspect accumulated history and statistics.

## Preconditions
- Docker Desktop running
- Ollama running on host machine (`http://host.docker.internal:11434`)
- model pulled in Ollama (`qwen2.5:3b`)

## Demo steps

### 1. Start stack
```bash
make up
make ps
```

### 2. Check service health
```bash
curl http://127.0.0.1:8080/health
```

Expected:
- `"status":"ok"`
- `"database":"ok"`
- `"models_loaded":1` or higher

### 3. Run business scenario: domain name generation
```bash
curl -X POST "http://127.0.0.1:8080/generate/domains" \
  -H "Content-Type: application/json" \
  -d '{
    "company": "онлайн платформа для регистрации доменов и хостинга",
    "keywords": ["domain", "hosting", "cloud"],
    "zone": ".ru",
    "count": 5
  }'
```

Expected:
- JSON with `domains` list and generated names ending with `.ru`

### 4. Show generic generation endpoint
```bash
curl -X POST "http://127.0.0.1:8080/generate" \
  -H "Content-Type: application/json" \
  -d '{"prompt":"Напиши краткое SEO-описание услуги VDS-хостинга"}'
```

### 5. Show streaming endpoint
```bash
curl -N -X POST "http://127.0.0.1:8080/generate/stream" \
  -H "Content-Type: application/json" \
  -d '{"prompt":"Напиши приветственное сообщение для нового клиента"}'
```

### 6. Show persisted history
```bash
curl "http://127.0.0.1:8080/history?limit=10"
```

### 7. Show analytics endpoint
```bash
curl "http://127.0.0.1:8080/stats"
```

Expected:
- total requests count
- average prompt length
- average answer length

## Interpretation for defense
- System works as an internal AI service for corporate workflows.
- No cloud LLM API required during runtime.
- API-first architecture supports integration with existing company systems.
- Generated content is auditable because all requests are logged in database.
