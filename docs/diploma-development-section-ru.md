# Раздел диплома «РЕАЛИЗАЦИЯ» по проекту `ai-servise`

> Раздел подготовлен как практический сценарий «что сделано в коде + что показывать на защите + какие команды выполнить». Текст ориентирован на демонстрацию **всего функционала**, включая поднятые службы, БД, API, gateway, OpenAI-совместимый слой и артефакты тестирования.

---

## 1. Общая характеристика реализации

В рамках реализации разработан backend-сервис на FastAPI, обеспечивающий:

- базовую генерацию текста;
- потоковую генерацию (NDJSON stream);
- генерацию доменных имен;
- FAQ-подсистему с импортом данных и контекстным ответом;
- генерацию PHP-файла по шаблону;
- gateway-кабинет (пользователи, модели, usage, админ-функции);
- OpenAI-совместимые эндпоинты (`/v1/models`, `/v1/chat/completions`).

Сервис разворачивается в Docker Compose связке `nginx + api + postgres`, с подключением Ollama как внешнего runtime и OpenRouter как внешнего OpenAI-совместимого провайдера.

---

## 2. Реализация инфраструктуры развертывания

### 2.1 Что реализовано

- `docker-compose.yml` поднимает:
  - `postgres` (персистентная БД, volume `pg_data`),
  - `api` (FastAPI приложение),
  - `nginx` (reverse proxy, внешний порт 8080).
- `Makefile` содержит команды быстрого управления стеком (`up`, `down`, `ps`, `logs`, `health`, `test`, `benchmark`).
- Используются переменные окружения (`.env`) для выбора моделей, ключей, URL провайдеров и прав администратора.

### 2.2 Что показать на защите (обязательно)

1. Стек поднят:
```bash
docker compose up -d --build
```
2. Контейнеры действительно работают:
```bash
docker compose ps
```
3. Проверка health:
```bash
curl http://127.0.0.1:8080/health
```
4. Проверка доступности API-документации:
- открыть `http://127.0.0.1:8080/docs`.

### 2.3 Какие скриншоты вставить

1. `docker compose ps` (видны `postgres`, `api`, `nginx` со статусом Up).
2. `curl /health` (JSON с `status: ok`, `database: ok`).
3. Swagger UI (`/docs`).
4. При желании: `docker compose logs --tail=100 api` (фрагмент логов).

---

## 3. Реализация уровня данных (PostgreSQL)

### 3.1 Что реализовано

В приложении используются основные сущности:

- `request_logs` — журнал генераций;
- `support_faq_entries` — база FAQ;
- `support_faq_query_metrics` — метрики качества FAQ;
- `gateway_users` — пользователи gateway;
- `ai_models_catalog` — каталог моделей и тарифов;
- `gateway_usage_logs` — журнал usage и стоимости.

### 3.2 Что показать на защите

Показать, что БД реально работает и данные сохраняются:

```bash
# пример входа в контейнер БД
docker compose exec postgres psql -U ${POSTGRES_USER:-ai_servise_user} -d ${POSTGRES_DB:-ai_servise_db}
```

Далее в psql:

```sql
\dt
SELECT COUNT(*) FROM request_logs;
SELECT COUNT(*) FROM support_faq_entries;
SELECT COUNT(*) FROM gateway_users;
SELECT COUNT(*) FROM gateway_usage_logs;
```

### 3.3 Какие скриншоты вставить

1. `\dt` со списком таблиц.
2. `SELECT COUNT(*) ...` по ключевым таблицам.
3. Пример строки из `gateway_usage_logs` после генерации через gateway.

---

## 4. Реализация базового API

### 4.1 Проверка работоспособности

```bash
curl http://127.0.0.1:8080/health
```

Что показать:
- статус сервиса;
- доступность базы;
- число загруженных моделей Ollama.

### 4.2 Синхронная генерация текста

```bash
curl -X POST "http://127.0.0.1:8080/generate" \
  -H "Content-Type: application/json" \
  -d '{"prompt":"Напиши краткое описание услуги VPS"}'
```

Что показать:
- JSON с `answer`.

### 4.3 Потоковая генерация (стриминг)

```bash
curl -N -X POST "http://127.0.0.1:8080/generate/stream" \
  -H "Content-Type: application/json" \
  -d '{"prompt":"Сгенерируй приветственное сообщение для клиента"}'
```

Что показать:
- постепенный приход чанков;
- завершающий chunk с `done=true`.

### 4.4 Генерация доменных имен

```bash
curl -X POST "http://127.0.0.1:8080/generate/domains" \
  -H "Content-Type: application/json" \
  -d '{
    "business_context":"регистрация доменов и хостинг",
    "keywords":["domain","hosting","cloud"],
    "zone":".ru",
    "count":5
  }'
```

Что показать:
- список `suggestions`,
- соответствие зоне `.ru`.

### 4.5 История и статистика

```bash
curl "http://127.0.0.1:8080/history?limit=10"
curl "http://127.0.0.1:8080/stats"
```

Что показать:
- накопление истории запросов;
- расчетные метрики (`total_requests`, `requests_last_24h`, FAQ-метрики).

### 4.6 Какие скриншоты вставить

1. `/generate` запрос/ответ.
2. `/generate/stream` (терминал с chunk-выводом).
3. `/generate/domains` (JSON со списком доменов).
4. `/history` и `/stats` (результаты после нескольких вызовов).

---

## 5. Реализация режима `/mode/run`

### 5.1 Что реализовано

Поддержаны режимы:

- `chat`;
- `domains`;
- `support_faq`.

`php_page` внутри `/mode/run` отключен по проектному решению (используется отдельный endpoint `POST /page-template/generate-file`).

### 5.2 Команды для демонстрации

```bash
# chat
curl -X POST "http://127.0.0.1:8080/mode/run" \
  -H "Content-Type: application/json" \
  -d '{"mode":"chat","payload":{"prompt":"Привет!"}}'

# domains
curl -X POST "http://127.0.0.1:8080/mode/run" \
  -H "Content-Type: application/json" \
  -d '{"mode":"domains","payload":{"business_context":"VPS и домены","zone":".ru","count":3}}'

# support_faq
curl -X POST "http://127.0.0.1:8080/mode/run" \
  -H "Content-Type: application/json" \
  -d '{"mode":"support_faq","payload":{"question":"Как продлить домен?"}}'
```

### 5.3 Что показать на защите

- единый вход `POST /mode/run`;
- корректную маршрутизацию логики в зависимости от `mode`;
- различный формат `result` по режимам.

### 5.4 Скриншоты

1. `mode=chat`.
2. `mode=domains`.
3. `mode=support_faq`.
4. Ошибка для `mode=php_page` (с пояснением, что используется отдельный endpoint).

---

## 6. Реализация FAQ-подсистемы

### 6.1 Импорт FAQ

```bash
curl -X POST "http://127.0.0.1:8080/support/faq/import" \
  -H "Content-Type: application/json" \
  -H "X-API-Key: <ADMIN_API_KEY>" \
  -d '{
    "items":[
      {"question":"Как продлить домен?","answer":"Продление в личном кабинете.","source":"support_chat"}
    ]
  }'
```

### 6.2 Импорт FAQ из диалога

```bash
curl -X POST "http://127.0.0.1:8080/support/dialogs/import" \
  -H "Content-Type: application/json" \
  -H "X-API-Key: <ADMIN_API_KEY>" \
  -d '{"transcript":"Q: Где DNS?\nA: DNS доступны в панели домена."}'
```

### 6.3 Ответ по FAQ

```bash
curl -X POST "http://127.0.0.1:8080/support/faq/ask" \
  -H "Content-Type: application/json" \
  -d '{"question":"Как продлить домен?","max_context_items":5}'
```

### 6.4 Что показать на защите

- что импорт действительно увеличивает базу FAQ;
- что ответ формируется с учетом релевантного контекста;
- что в `/stats` меняются FAQ-метрики качества.

### 6.5 Скриншоты

1. успешный импорт FAQ;
2. успешный импорт диалогов;
3. ответ `/support/faq/ask`;
4. FAQ-метрики в `/stats`.

---

## 7. Реализация шаблонной генерации PHP

### 7.1 Генерация файла

```bash
curl -X POST "http://127.0.0.1:8080/page-template/generate-file" \
  -H "Content-Type: application/json" \
  -d '{
    "template_name":"hosting.php",
    "content_prompt":"Сделай продающий текст для страницы хостинга",
    "output_filename":"hosting-generated.php"
  }' \
  --output hosting-generated.php
```

### 7.2 Что показать

- endpoint возвращает именно файл;
- в `Content-Disposition` выставлено имя файла;
- содержимое действительно сгенерировано по шаблону.

### 7.3 Скриншоты

1. команда генерации;
2. результат `ls -lh hosting-generated.php`;
3. первые строки файла (`head -n 40 hosting-generated.php`).

---

## 8. Реализация gateway-подсистемы

### 8.1 Демонстрация пользовательского сценария

#### 1) Регистрация
```bash
curl -X POST "http://127.0.0.1:8080/gateway/register" \
  -H "Content-Type: application/json" \
  -d '{"email":"user@example.com","password":"strong-pass-123"}'
```

#### 2) Логин
```bash
curl -X POST "http://127.0.0.1:8080/gateway/login" \
  -H "Content-Type: application/json" \
  -d '{"email":"user@example.com","password":"strong-pass-123"}'
```

#### 3) Получение каталога моделей
```bash
curl -X GET "http://127.0.0.1:8080/gateway/models" \
  -H "X-Gateway-Key: <GATEWAY_KEY>"
```

#### 4) Генерация через gateway
```bash
curl -X POST "http://127.0.0.1:8080/gateway/generate" \
  -H "Content-Type: application/json" \
  -H "X-Gateway-Key: <GATEWAY_KEY>" \
  -d '{"model_id":"local/qwen2.5-3b","prompt":"Напиши план запуска хостинга","max_tokens":180}'
```

#### 5) История usage
```bash
curl -X GET "http://127.0.0.1:8080/gateway/usage" \
  -H "X-Gateway-Key: <GATEWAY_KEY>"
```

### 8.2 Что показать

- создание пользователя;
- выдачу API-ключа;
- список локальных/внешних моделей;
- ответ генерации с `prompt_tokens`, `completion_tokens`, `total_tokens`, `tokens_spent`;
- запись usage в истории.

### 8.3 Скриншоты UI (обязательные)

1. `/gateway/register`
2. `/gateway/login`
3. `/gateway/profile`
4. `/gateway/models/page`
5. `/gateway/model/local%2Fqwen2.5-3b`
6. `/gateway/model/local%2Fllama3.2-3b`
7. `/gateway/model/proxy%2Fopenrouter-deepseek-chat`
8. `/gateway/history`
9. `/gateway/admin`

---

## 9. Реализация административного gateway-функционала

### 9.1 Команды

```bash
# список пользователей
curl -X GET "http://127.0.0.1:8080/gateway/admin/users" \
  -H "X-Gateway-Key: <ADMIN_GATEWAY_KEY>"

# список моделей
curl -X GET "http://127.0.0.1:8080/gateway/admin/models" \
  -H "X-Gateway-Key: <ADMIN_GATEWAY_KEY>"

# создание модели
curl -X POST "http://127.0.0.1:8080/gateway/admin/models" \
  -H "Content-Type: application/json" \
  -H "X-Gateway-Key: <ADMIN_GATEWAY_KEY>" \
  -d '{
    "model_id":"proxy/demo-model",
    "display_name":"Demo Proxy Model",
    "provider":"openai",
    "target_model":"openai/gpt-4o-mini",
    "price_per_1k_tokens":10,
    "markup_percent":20,
    "is_active":true
  }'
```

### 9.2 Что показать

- role-based контроль доступа (обычный user не должен пройти admin-endpoints);
- управление каталогом моделей;
- управление пользователями.

### 9.3 Скриншоты

1. `GET /gateway/admin/users` (успешный ответ админа);
2. `403` при попытке обычным ключом;
3. `GET /gateway/admin/models`.

---

## 10. Реализация OpenAI-совместимого слоя (через OpenRouter)

### 10.1 Получение моделей

```bash
curl -X GET "http://127.0.0.1:8080/v1/models" \
  -H "Authorization: Bearer <GATEWAY_KEY>"
```

### 10.2 Chat completions

```bash
curl -X POST "http://127.0.0.1:8080/v1/chat/completions" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer <GATEWAY_KEY>" \
  -d '{
    "model":"proxy/openrouter-deepseek-chat",
    "messages":[{"role":"user","content":"Сделай план запуска хостинг-проекта"}],
    "max_tokens":180,
    "temperature":0.3
  }'
```

### 10.3 Что показать

- формат ответа OpenAI-compatible (`choices`, `usage`);
- что backend внутри использует gateway-слой;
- что внешний провайдер — OpenRouter.

### 10.4 Скриншоты

1. `/v1/models`;
2. `/v1/chat/completions`;
3. подтверждение usage-лога после вызова.

---

## 11. Реализация тестирования и верификации

### 11.1 Автотесты

```bash
python3 -m pytest -q
```

Что показать:
- количество тестов;
- статус `passed`.

### 11.2 Нагрузочные замеры

```bash
# базовый API
python3 scripts/benchmark_api.py \
  --url http://127.0.0.1:8080/generate \
  --requests 20 \
  --warmup 3 \
  --out docs/results/benchmark-generate.json

# gateway по 3 моделям
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

Что показать:
- `status_codes`, `success_rate_percent`;
- latency (`avg`, `p95`, `p99`);
- token-метрики по моделям;
- наличие/отсутствие ошибок.

### 11.3 Скриншоты

1. вывод `pytest`;
2. фрагмент benchmark JSON;
3. таблица сравнения моделей в дипломе.

---

## 12. Полный сценарий показа «все что есть» (порядок для защиты)

1. `docker compose up -d --build`
2. `docker compose ps`
3. `curl /health`
4. Swagger `/docs`
5. `/generate`
6. `/generate/stream`
7. `/generate/domains`
8. `/history` и `/stats`
9. `/support/faq/import` -> `/support/faq/ask`
10. `/page-template/generate-file`
11. gateway register/login/models/generate/usage
12. gateway admin users/models
13. `/v1/models` + `/v1/chat/completions`
14. проверка БД через `psql` (`\dt`, `COUNT(*)`)
15. `pytest`
16. `benchmark_api.py` + `benchmark_gateway_models.py`

Этот порядок закрывает весь функционал системы, включая инфраструктуру, БД, API, UI, безопасность ролей и метрики.

---

## 13. Чек-лист скриншотов для приложения к диплому

### 13.1 Инфраструктура

- [ ] `docker compose ps`
- [ ] `curl /health`
- [ ] Swagger `/docs`

### 13.2 Базовый API

- [ ] `/generate`
- [ ] `/generate/stream`
- [ ] `/generate/domains`
- [ ] `/history`
- [ ] `/stats`

### 13.3 FAQ + шаблоны

- [ ] `/support/faq/import`
- [ ] `/support/dialogs/import`
- [ ] `/support/faq/ask`
- [ ] `/page-template/generate-file`

### 13.4 Gateway

- [ ] `/gateway/register`
- [ ] `/gateway/login`
- [ ] `/gateway/profile`
- [ ] `/gateway/models/page`
- [ ] `/gateway/model/local%2Fqwen2.5-3b`
- [ ] `/gateway/model/local%2Fllama3.2-3b`
- [ ] `/gateway/model/proxy%2Fopenrouter-deepseek-chat`
- [ ] `/gateway/history`
- [ ] `/gateway/admin`
- [ ] `/gateway/admin/users` (API)
- [ ] `/gateway/admin/models` (API)

### 13.5 OpenAI-compatible

- [ ] `/v1/models`
- [ ] `/v1/chat/completions`

### 13.6 База данных и тесты

- [ ] `\dt` в psql
- [ ] `COUNT(*)` по ключевым таблицам
- [ ] `pytest`
- [ ] benchmark JSON-файлы

---

## 14. Итог по разделу «Реализация»

В результате реализации создан полнофункциональный AI-сервис с воспроизводимым развертыванием, персистентным хранением данных, набором прикладных API-режимов, gateway-слоем для продуктового доступа к моделям и OpenAI-совместимым интерфейсом для внешних клиентов. Реализация подтверждается демонстрационными сценариями, сохранением данных в БД, автотестами и нагрузочными замерами.

