# ai-servise
 
Локальный API-сервис генерации текста на FastAPI + Ollama + PostgreSQL.
 
## Запуск
 
1. Поднять PostgreSQL:
```bash
docker compose up -d
Создать .env:

cp .env.example .env
Установить зависимости:

python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
Запуск API:

uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
Проверка
Health:

curl http://127.0.0.1:8000/health
Генерация (POST):

curl -X POST "http://127.0.0.1:8000/generate" \
  -H "Content-Type: application/json" \
  -d '{"prompt":"Привет, предложи 3 доменных имени для IT-сервиса"}'
История:

curl "http://127.0.0.1:8000/history?limit=5"
