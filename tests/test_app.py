import os
import tempfile

os.environ["DATABASE_URL"] = "sqlite:////tmp/ai_servise_test.db"
os.environ["OLLAMA_HOST"] = "http://fake-ollama"
os.environ["OLLAMA_MODEL"] = "qwen2.5:3b"
os.environ["LOG_LEVEL"] = "INFO"

from fastapi.testclient import TestClient
import app.main as main_module
from app.db import Base, engine
from app.models import SupportFaqEntry

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


def test_mode_php_template():
    template = "<html><body><h1>{{title}}</h1><p>{{content}}</p></body></html>"
    r = client.post(
        "/mode/run",
        json={
            "mode": "php_page",
            "payload": {
                "content_prompt": "Услуга VPS-хостинга",
                "template_html": template,
            },
        },
    )
    assert r.status_code == 200
    output = r.json()["result"]["php_page"]
    assert "<html>" in output
    assert "{{content}}" not in output
    assert "{{content}}" not in output


def test_mode_php_page_by_template_name():
    r = client.post(
        "/mode/run",
        json={
            "mode": "php_page",
            "payload": {
                "template_name": "hosting",
                "content_prompt": "Подготовь продающий текст для страницы хостинга",
            },
        },
    )
    assert r.status_code == 200
    result = r.json()["result"]
    assert "php_page" in result
    assert "template_name" in result
    assert result["template_name"] == "hosting"
    assert "{{AI_HERO_TITLE}}" not in result["php_page"]


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
    fd, path = tempfile.mkstemp(prefix="support_dialog_", suffix=".csv")
    os.close(fd)
    try:
        with open(path, "w", encoding="utf-8") as f:
            f.write(
                "question,answer\n"
                "\"Где найти DNS?\",\"DNS доступны в панели управления доменом.\""
            )
        with open(path, "r", encoding="utf-8") as f:
            csv_text = f.read()
        r = client.post(
            "/support/faq/import",
            json={
                "items": [
                    {
                        "question": "Где найти DNS?",
                        "answer": "DNS доступны в панели управления доменом.",
                        "source": "support_chat",
                    }
                ]
            },
        )
        assert r.status_code == 200
        assert r.json()["imported"] >= 1
    finally:
        if os.path.exists(path):
            os.remove(path)
