# Чек-лист для большого отчета и защиты (ai-servise)

Документ для подготовки курсовой/дипломной защиты по проекту `ai-servise`.

---

## 1) Что показать преподавателю (короткий план защиты)

1. **Архитектура сервиса**
   - Nginx -> FastAPI -> Ollama/OpenRouter -> PostgreSQL.
   - Поддержка веб-кабинета и API.
2. **4 прикладных режима**
   - чат;
   - генерация доменов;
   - генерация PHP-страницы по шаблону (файлом);
   - FAQ-ассистент.
3. **Gateway как единая точка доступа к моделям**
   - локальные и внешние модели;
   - роль администратора;
   - история запросов и метрики использования.
4. **Набор тестов + воспроизводимые бенчмарки**
   - автотесты (`pytest`);
   - нагрузочные замеры в JSON для отчета.

---

## 2) Артефакты, которые должны быть в отчете

### Обязательно приложить

- Скриншоты UI:
  - `/gateway/register`
  - `/gateway/login`
  - `/gateway/profile`
  - `/gateway/models/page`
  - `/gateway/model/local%2Fqwen2.5-3b`
  - `/gateway/model/local%2Fllama3.2-3b`
  - `/gateway/model/proxy%2Fopenrouter-deepseek-chat`
  - `/gateway/history`
  - `/gateway/admin`
- Скриншот Swagger: `/docs`.
- Скриншот успешного `ollama list` (две локальные модели).
- JSON с результатами бенчмарков из `docs/results/`.
- Вывод `python3 -m pytest -q`.

### Полезно приложить

- Фрагмент `docker compose ps`.
- Пример данных из `/stats`.
- Пример запроса/ответа для каждого режима.

---

## 3) Быстрая проверка перед замерами

1. Запустить стек:

```bash
docker compose up -d --build
docker compose ps
```

2. Проверить здоровье:

```bash
curl http://127.0.0.1:8080/health
```

3. Проверить локальные модели (там, где запущен Ollama):

```bash
ollama list
```

Ожидаются:
- `qwen2.5:3b`
- `llama3.2:3b`

4. Проверить gateway-модели:

```bash
curl -X POST "http://127.0.0.1:8080/gateway/register" \
  -H "Content-Type: application/json" \
  -d '{"email":"report.user@example.com","password":"strong-pass-123"}'
```

Скопировать `api_key`, затем:

```bash
curl -X GET "http://127.0.0.1:8080/gateway/models" \
  -H "X-Gateway-Key: asv_...key..."
```

Ожидаются model_id:
- `local/qwen2.5-3b`
- `local/llama3.2-3b`
- `proxy/openrouter-deepseek-chat`

---

## 4) Прогон автотестов (для раздела «верификация»)

```bash
python3 -m pytest -q
```

В отчет:
- общее число тестов;
- статус (passed/failed);
- дата и окружение запуска.

---

## 5) Замеры метрик по 3 моделям (главный эксперимент)

Используется скрипт:
- `scripts/benchmark_gateway_models.py`

### Базовый запуск

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

### Что получите

JSON с метриками **по каждой модели**:
- `status_codes`
- `success_rate_percent`
- `latency_ms`: min/avg/median/p95/p99/max
- `response_size_bytes.avg`
- `tokens.avg_prompt_tokens`
- `tokens.avg_completion_tokens`
- `tokens.avg_total_tokens`
- `errors` (если были)

---

## 6) Замеры качества по режимам и моделям

Используется скрипт:
- `scripts/benchmark_modes_quality.py`

Пример запуска:

```bash
python3 scripts/benchmark_modes_quality.py \
  --base-url http://127.0.0.1:8080 \
  --email quality.benchmark@example.com \
  --password strong-pass-123 \
  --models "local/qwen2.5-3b,local/llama3.2-3b" \
  --requests 10 \
  --warmup 2 \
  --out docs/results/benchmark-modes-quality.json
```

Если у вас включен `ADMIN_API_KEY`, добавьте:

```bash
  --admin-api-key your-admin-key
```

Что измеряется:

- `chat`: средняя длина ответа, число пустых ответов;
- `domains`: среднее число валидных доменов и попадание в нужную зону;
- `support_faq`: `matched_items`, `relevance_avg`, `relevance_max`, `zero_match_rate`;
- `php_template_file`: размер результата, наличие PHP/HTML тегов.

---

## 7) Как оформить таблицы в курсовой

Рекомендуемые таблицы:

1. **Таблица стабильности**
   - модель;
   - % успешных ответов;
   - распределение HTTP-кодов.

2. **Таблица производительности**
   - модель;
   - avg latency;
   - p95;
   - p99;
   - max.

3. **Таблица ресурсоемкости**
   - модель;
   - средние prompt/completion/total tokens;
   - средний размер ответа.

4. **Сравнительный вывод**
   - где ниже задержка;
   - где стабильнее ответы;
   - где выше/ниже токенопотребление.

---

## 8) Демо-сценарий на защите (5-7 минут)

1. Показ `/health`.
2. Показ регистрации/логина в gateway.
3. Показ страницы моделей.
4. По одному короткому запросу:
   - локальная `qwen2.5:3b`,
   - локальная `llama3.2:3b`,
   - внешняя `deepseek/deepseek-chat`.
5. Показ режима генерации доменов.
6. Показ FAQ-режима (после `faq/import`).
7. Показ генерации PHP-файла по шаблону.
8. Показ истории (`/gateway/history`) и `/stats`.
9. Показ JSON-файла бенчмарка и итоговой таблицы сравнения.

---

## 9) Типичные проблемы и как объяснить в отчете

1. `model 'llama3.2:3b' not found`
   - причина: API смотрит в Ollama daemon без этой модели;
   - решение: проверить `OLLAMA_HOST`, `ollama list`, перезапуск контейнеров.

2. Ошибки внешней модели
   - причина: неверный/пустой `OPENAI_API_KEY` (ключ OpenRouter);
   - решение: задать валидный `sk-or-v1-...`, перезапустить сервис.

3. Пустые/нулевые метрики
   - причина: бенчмарк не запускался на рабочем API;
   - решение: прогнать `benchmark_gateway_models.py` и сохранить JSON в `docs/results/`.

---

## 10) Минимальный список файлов для приложения к отчету

- `README.md`
- `docs/architecture.md`
- `docs/experiment-methodology.md`
- `docs/defense-scenario.md`
- `docs/report-checklist-ru.md`
- `docs/security-notes-ru.md`
- `docs/results/benchmark-gateway-3models.json`
- `docs/results/benchmark-modes-quality.json`
- скриншоты интерфейса и вывода команд

