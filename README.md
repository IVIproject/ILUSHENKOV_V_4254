# Разработка локальной системы генерации текстового контента с применением искусственного интеллекта

`ai-servise` — это API‑сервис на FastAPI для корпоративных сценариев с ИИ:

- чат-режим;
- генерация доменных имен;
- генерация PHP-страницы по шаблону (с выдачей файла);
- FAQ-ассистент по базе вопросов/ответов;
- gateway-кабинет с локальными и внешними моделями.

## 1. Технологический стек

- **FastAPI** — API и Swagger (`/docs`);
- **PostgreSQL** — хранение логов и FAQ-данных;
- **Ollama** — локальные модели;
- **OpenRouter** — внешняя модель через OpenAI-совместимый интерфейс;
- **Nginx** — reverse proxy;
- **Docker Compose** — запуск всего стека.

---

## 2. Что умеет проект

### 2.1 Основные API-эндпоинты

- `GET /health` — проверка состояния;
- `POST /generate` — обычная генерация текста;
- `POST /generate/stream` — потоковая генерация;
- `POST /generate/domains` — генерация доменных имен;
- `POST /mode/run` — унифицированный запуск режимов:
  - `chat`
  - `domains`
  - `support_faq`
- `POST /page-template/generate-file` — генерация PHP-файла из шаблона;
- `POST /support/faq/import` — импорт FAQ;
- `POST /support/dialogs/import` — импорт FAQ из диалогов;
- `POST /support/faq/ask` — ответ по FAQ;
- `GET /history` — история запросов;
- `GET /stats` — статистика.

### 2.2 Gateway (кабинет и API-ключи)

- регистрация и логин пользователей;
- выдача `X-Gateway-Key`;
- каталог моделей (локальные + внешние);
- генерация через `/gateway/generate`;
- история использования;
- админ-панель `/gateway/admin`:
  - пользователи;
  - модели.

### 2.3 OpenAI-совместимый интерфейс

- `GET /v1/models`
- `POST /v1/chat/completions`

Авторизация: `Authorization: Bearer <X-Gateway-Key>`.

---

## 3. Быстрый старт (Docker)

### 3.1 Подготовка

```bash
cp .env.example .env
nano .env
```

### 3.2 Запуск

```bash
docker compose up -d --build
docker compose ps
```

После запуска:

- API: `http://127.0.0.1:8080`
- Swagger: `http://127.0.0.1:8080/docs`

Проверка:

```bash
curl http://127.0.0.1:8080/health
```

---

## 4. Настройка моделей

## 4.1 Локальные модели Ollama

Нужны:

- `qwen2.5:3b`
- `llama3.2:3b`

Если отсутствуют:

```bash
ollama pull qwen2.5:3b
ollama pull llama3.2:3b
```

### 4.2 Внешняя модель (OpenRouter)

В проекте уже преднастроена модель:

- `proxy/openrouter-deepseek-chat` -> `deepseek/deepseek-chat`

Нужно только задать валидный:

```env
OPENAI_API_KEY=sk-or-v1-...
```

---

## 5. Веб-маршруты кабинета

- `/gateway` -> редирект на `/gateway/login`
- `/gateway/register` — регистрация
- `/gateway/login` — авторизация
- `/gateway/profile` — профиль
- `/gateway/models/page` — список моделей
- `/gateway/model/{model_id}` — страница модели
- `/gateway/history` — история
- `/gateway/admin` — управление (для администратора)

---

## 6. Примеры API-запросов

### 6.1 Регистрация gateway-пользователя

```bash
curl -X POST "http://127.0.0.1:8080/gateway/register" \
  -H "Content-Type: application/json" \
  -d '{"email":"user@example.com","password":"strong-pass-123"}'
```

### 6.2 Получить список моделей

```bash
curl -X GET "http://127.0.0.1:8080/gateway/models" \
  -H "X-Gateway-Key: asv_...your_key..."
```

### 6.3 Генерация через локальную модель

```bash
curl -X POST "http://127.0.0.1:8080/gateway/generate" \
  -H "Content-Type: application/json" \
  -H "X-Gateway-Key: asv_...your_key..." \
  -d '{"model_id":"local/qwen2.5-3b","prompt":"Кратко опиши услугу VPS"}'
```

### 6.4 Генерация через OpenRouter

```bash
curl -X POST "http://127.0.0.1:8080/gateway/generate" \
  -H "Content-Type: application/json" \
  -H "X-Gateway-Key: asv_...your_key..." \
  -d '{"model_id":"proxy/openrouter-deepseek-chat","prompt":"Сделай план запуска проекта"}'
```

### 6.5 Генерация PHP-файла из шаблона

```bash
curl -X POST "http://127.0.0.1:8080/page-template/generate-file" \
  -H "Content-Type: application/json" \
  -d '{"template_name":"hosting.php","content_prompt":"Сделай продающий текст для страницы хостинга","output_filename":"hosting-generated.php"}' \
  --output hosting-generated.php
```

---

## 7. `ADMIN_API_KEY` и админ-доступ

### 7.1 `ADMIN_API_KEY`

Используется только для:

- `POST /support/faq/import`
- `POST /support/dialogs/import`

Если ключ задан в `.env`, нужно передавать:

```http
X-API-Key: <ваш ADMIN_API_KEY>
```

### 7.2 Админ в gateway

Права администратора в gateway назначаются по email:

```env
GATEWAY_ADMIN_EMAILS=admin@example.com,owner@example.com
```

Если пользователь входит с таким email, он становится администратором и может работать с `/gateway/admin`.

---

## 8. Тестирование

### 8.1 Автотесты

```bash
python3 -m pytest -q
```

### 8.2 Бенчмарк базового API

```bash
python3 scripts/benchmark_api.py \
  --url http://127.0.0.1:8080/generate \
  --requests 20 \
  --warmup 3 \
  --out docs/results/benchmark-generate.json
```

### 8.3 Бенчмарк gateway по 3 моделям (для отчета)

```bash
python3 scripts/benchmark_gateway_models.py \
  --base-url http://127.0.0.1:8080 \
  --email benchmark.user@example.com \
  --password strong-pass-123 \
  --models "local/qwen2.5-3b,local/llama3.2-3b,proxy/openrouter-deepseek-chat" \
  --requests 20 \
  --warmup 3 \
  --max-tokens 180 \
  --out docs/results/benchmark-gateway-3models.json
```

## 9. Полезные команды Makefile

```bash
make up
make ps
make health
make test
make benchmark
make logs
make down
```

---
