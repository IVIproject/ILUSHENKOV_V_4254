import os
os.environ["DATABASE_URL"] = "sqlite:////tmp/ai_servise_test.db"
os.environ["OLLAMA_HOST"] = "http://fake-ollama"
os.environ["OLLAMA_MODEL"] = "qwen2.5:3b"
os.environ["LOG_LEVEL"] = "INFO"

from fastapi.testclient import TestClient
import app.main as main_module
from app.db import Base, engine
from app.models import SupportFaqEntry, SupportFaqQueryMetric

class FakeClient:
    def list(self):
        return {"models": [{"name": "qwen2.5:3b"}]}

    def chat(self, model, messages, stream=False):
        text = messages[0]["content"]
        if "Generate ONLY domain names" in text:
            return {
                "message": {
                    "content": "cloudhost.ru\nfastvps.ru\nsecurezone.ru\n"
                }
            }
        if "Generate ONLY page text content" in text:
            return {
                "message": {
                    "content": "Надежный VPS-хостинг для бизнеса. Быстрый запуск и поддержка 24/7."
                }
            }
        if "technical support assistant" in text:
            return {
                "message": {
                    "content": "Продлить домен можно в личном кабинете в разделе управления услугами."
                }
            }
        if stream:
            def _iter():
                yield {"message": {"content": "part1 "}}
                yield {"message": {"content": "part2"}}

            return _iter()

        return {"message": {"content": f"fake answer for: {text}"}}

main_module.client = FakeClient()
Base.metadata.create_all(bind=engine)


def _clear_faq_table():
    with main_module.SessionLocal() as db:
        db.query(SupportFaqQueryMetric).delete()
        db.query(SupportFaqEntry).delete()
        db.commit()

client = TestClient(main_module.app)

def test_health():
    r = client.get("/health")
    assert r.status_code == 200
    data = r.json()
    assert data["status"] == "ok"
    assert data["database"] == "ok"
    assert "x-request-id" in r.headers

def test_generate_and_history():
    r = client.post("/generate", json={"prompt": "hello"})
    assert r.status_code == 200
    assert "answer" in r.json()

    h = client.get("/history?limit=1")
    assert h.status_code == 200
    assert isinstance(h.json(), list)


def test_generate_stream():
    r = client.post("/generate/stream", json={"prompt": "stream me"})
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("application/x-ndjson")
    lines = [line for line in r.text.splitlines() if line.strip()]
    assert len(lines) >= 1
    assert '"chunk":"part1 "' in lines[0]


def test_generate_domains():
    r = client.post(
        "/generate/domains",
        json={
            "business_context": "My Hosting Service",
            "keywords": ["cloud", "fast", "secure"],
            "zone": ".ru",
            "count": 3,
        },
    )
    assert r.status_code == 200
    data = r.json()
    assert data["zone"] == ".ru"
    assert data["business_context"] == "My Hosting Service"
    assert len(data["suggestions"]) == 3
    assert all(item.endswith(".ru") for item in data["suggestions"])


def test_stats():
    client.post("/generate", json={"prompt": "stats seed"})
    r = client.get("/stats")
    assert r.status_code == 200
    data = r.json()
    assert "total_requests" in data
    assert data["total_requests"] >= 1
    assert "requests_last_24h" in data
    assert "support_faq_total_requests" in data
    assert "support_faq_no_match_rate" in data
    assert "support_faq_avg_relevance_score" in data
    assert isinstance(data["support_faq_top_questions"], list)


def test_mode_chat():
    r = client.post(
        "/mode/run",
        json={"mode": "chat", "payload": {"prompt": "Привет!"}},
    )
    assert r.status_code == 200
    data = r.json()
    assert data["mode"] == "chat"
    assert isinstance(data["result"]["text"], str)


def test_mode_domains_list():
    r = client.post(
        "/mode/run",
        json={
            "mode": "domains",
            "payload": {
                "business_context": "Сервис регистрации доменов",
                "zone": ".ru",
                "count": 3,
            },
        },
    )
    assert r.status_code == 200
    out = r.json()["result"]["suggestions"]
    assert len(out) == 3
    assert all(x.endswith(".ru") for x in out)
    assert all(" " not in x for x in out)


def test_mode_php_page_removed_from_mode_runner():
    r = client.post(
        "/mode/run",
        json={
            "mode": "php_page",
            "payload": {"content_prompt": "Услуга VPS-хостинга"},
        },
    )
    assert r.status_code == 400
    assert "POST /page-template/generate-file" in r.json()["detail"]


def test_page_template_generate_file():
    r = client.post(
        "/page-template/generate-file",
        json={
            "template_name": "hosting",
            "content_prompt": "Сделай текст лендинга хостинга",
            "output_filename": "generated-hosting.php",
        },
    )
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("application/x-httpd-php")
    disposition = r.headers.get("content-disposition", "")
    assert "generated-hosting.php" in disposition
    assert "<?" in r.text


def test_faq_import_and_support_mode():
    _clear_faq_table()
    items = [
        {
            "question": "Как продлить домен?",
            "answer": "Продлить домен можно в личном кабинете.",
            "source": "support_chat",
        }
    ]
    r_import = client.post("/support/faq/import", json={"items": items})
    assert r_import.status_code == 200
    assert r_import.json()["imported"] >= 1

    r_mode = client.post(
        "/mode/run",
        json={
                "mode": "support_faq",
            "payload": {"question": "Как продлить домен?"},
        },
    )
    assert r_mode.status_code == 200
    data = r_mode.json()
    assert data["mode"] == "support_faq"
    assert "личном кабинете" in data["result"]["answer"]


def test_support_dialog_import():
    _clear_faq_table()
    r = client.post(
        "/support/dialogs/import",
        json={"transcript": "Q: Где найти DNS?\nA: DNS доступны в панели управления доменом."},
    )
    assert r.status_code == 200
    assert r.json()["parsed_pairs"] >= 1
    assert r.json()["imported"] >= 1


def test_support_faq_relevance_limit():
    _clear_faq_table()
    r_import = client.post(
        "/support/faq/import",
        json={
            "items": [
                {
                    "question": "Как настроить DNS-записи?",
                    "answer": "Откройте раздел DNS в панели домена.",
                    "source": "support_chat",
                },
                {
                    "question": "Как получить счет на оплату?",
                    "answer": "Счет доступен в разделе Финансы.",
                    "source": "support_chat",
                },
            ]
        },
    )
    assert r_import.status_code == 200

    r = client.post(
        "/support/faq/ask",
        json={"question": "Где изменить DNS?", "max_context_items": 1},
    )
    assert r.status_code == 200
    assert r.json()["matched_items"] == 1

    stats = client.get("/stats")
    assert stats.status_code == 200
    metrics = stats.json()
    assert metrics["support_faq_total_requests"] >= 1
    assert metrics["support_faq_avg_relevance_score"] >= 0.0


def test_admin_api_key_protects_import_endpoints():
    _clear_faq_table()
    previous = main_module.settings.admin_api_key
    main_module.settings.admin_api_key = "secret-key"
    try:
        r_unauthorized = client.post(
            "/support/faq/import",
            json={
                "items": [
                    {
                        "question": "Question one",
                        "answer": "Answer one",
                        "source": "support_chat",
                    }
                ]
            },
        )
        assert r_unauthorized.status_code == 401

        r_authorized = client.post(
            "/support/faq/import",
            headers={"X-API-Key": "secret-key"},
            json={
                "items": [
                    {
                        "question": "Question 2",
                        "answer": "Answer 2",
                        "source": "support_chat",
                    }
                ]
            },
        )
        assert r_authorized.status_code == 200

        r_dialog_unauthorized = client.post(
            "/support/dialogs/import",
            json={"transcript": "Q: Где DNS?\nA: В панели домена."},
        )
        assert r_dialog_unauthorized.status_code == 401
    finally:
        main_module.settings.admin_api_key = previous
