import os
os.environ["DATABASE_URL"] = "sqlite:////tmp/ai_servise_test.db"
os.environ["OLLAMA_HOST"] = "http://fake-ollama"
os.environ["OLLAMA_MODEL"] = "qwen2.5:3b"
os.environ["LOG_LEVEL"] = "INFO"
os.environ["GATEWAY_PROVIDER_API_KEY"] = "test-provider-key"

from fastapi.testclient import TestClient
import app.main as main_module
from app.db import Base, engine
from app.models import (
    SupportFaqEntry,
    SupportFaqQueryMetric,
    GatewayModel,
    GatewayUser,
    GatewayUsageLog,
    GatewayBalanceAuditLog,
)

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
        if "Как защитить API" in text:
            return {
                "message": {"content": "Используйте API-ключи, лимиты и аудит запросов."}
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
        db.query(GatewayBalanceAuditLog).delete()
        db.query(GatewayUsageLog).delete()
        db.query(SupportFaqEntry).delete()
        db.query(GatewayModel).delete()
        db.query(GatewayUser).delete()
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


def test_gateway_register_models_and_generate():
    _clear_faq_table()
    register = client.post(
        "/gateway/register",
        json={"email": "user@example.com", "password": "strong-pass-123"},
    )
    assert register.status_code == 200
    data = register.json()
    assert data["token_balance"] == 0
    assert data["api_key"]

    gateway_key = data["api_key"]
    headers = {"X-Gateway-Key": gateway_key}

    topup = client.post("/gateway/tokens/topup", headers=headers, json={"tokens": 5000})
    assert topup.status_code == 200
    assert topup.json()["token_balance"] == 5000

    models_resp = client.get("/gateway/models", headers=headers)
    assert models_resp.status_code == 200
    model_ids = [m["model_id"] for m in models_resp.json()["models"]]
    assert "local/qwen2.5-3b" in model_ids
    assert "local/llama3.2-3b" in model_ids
    assert "proxy/openai-gpt-4o-mini" in model_ids

    generate = client.post(
        "/gateway/generate",
        headers=headers,
        json={"model_id": "local/qwen2.5-3b", "prompt": "Как защитить API?", "max_tokens": 120},
    )
    assert generate.status_code == 200
    out = generate.json()
    assert "answer" in out
    assert out["provider"] == "ollama"
    assert out["tokens_spent"] > 0
    assert out["token_balance"] < 5000


def test_gateway_login_me_and_usage():
    _clear_faq_table()
    register = client.post(
        "/gateway/register",
        json={"email": "login@example.com", "password": "strong-pass-123", "tariff_code": "business"},
    )
    assert register.status_code == 200
    api_key = register.json()["api_key"]

    login = client.post(
        "/gateway/login",
        json={"email": "login@example.com", "password": "strong-pass-123"},
    )
    assert login.status_code == 200
    assert login.json()["api_key"] == api_key
    headers = {"X-Gateway-Key": api_key}

    me = client.get("/gateway/me", headers=headers)
    assert me.status_code == 200
    me_payload = me.json()
    assert me_payload["email"] == "login@example.com"
    assert me_payload["tariff_code"] == "business"

    topup = client.post("/gateway/tokens/topup", headers=headers, json={"tokens": 6000})
    assert topup.status_code == 200

    generate = client.post(
        "/gateway/generate",
        headers=headers,
        json={"model_id": "local/qwen2.5-3b", "prompt": "Тест usage", "max_tokens": 100},
    )
    assert generate.status_code == 200

    usage = client.get("/gateway/usage?limit=5", headers=headers)
    assert usage.status_code == 200
    items = usage.json()["items"]
    assert len(items) >= 1
    assert items[0]["model_id"] == "local/qwen2.5-3b"
    assert items[0]["tokens_spent"] >= 1


def test_gateway_balance_audit_user_and_admin():
    _clear_faq_table()
    previous_gateway_admin = main_module.settings.gateway_admin_api_key
    previous_admin = main_module.settings.admin_api_key
    main_module.settings.gateway_admin_api_key = "gateway-admin-test-key"
    main_module.settings.admin_api_key = None
    try:
        register = client.post(
            "/gateway/register",
            json={"email": "audit@example.com", "password": "strong-pass-123", "tariff_code": "starter"},
        )
        assert register.status_code == 200
        user_payload = register.json()
        user_id = user_payload["user_id"]
        user_headers = {"X-Gateway-Key": user_payload["api_key"]}

        topup = client.post("/gateway/tokens/topup", headers=user_headers, json={"tokens": 1500})
        assert topup.status_code == 200

        user_audit = client.get("/gateway/audit/balance?limit=10", headers=user_headers)
        assert user_audit.status_code == 200
        user_items = user_audit.json()["items"]
        assert len(user_items) >= 1
        assert user_items[0]["action"] == "self_topup"
        assert user_items[0]["delta_tokens"] == 1500
        assert user_items[0]["actor"] == "user"

        admin_headers = {"X-Gateway-Admin-Key": "gateway-admin-test-key"}
        update = client.patch(
            f"/gateway/admin/users/{user_id}",
            headers=admin_headers,
            json={"add_tokens": 300, "balance_reason": "bonus for testing"},
        )
        assert update.status_code == 200

        admin_audit = client.get("/gateway/admin/audit/balance?limit=20", headers=admin_headers)
        assert admin_audit.status_code == 200
        all_items = admin_audit.json()["items"]
        assert any(item["action"] == "admin_adjustment" for item in all_items)
        adjusted = next(item for item in all_items if item["action"] == "admin_adjustment")
        assert adjusted["actor"] == "admin"
        assert adjusted["reason"] == "bonus for testing"

        filtered = client.get(
            f"/gateway/admin/audit/balance?limit=20&user_id={user_id}",
            headers=admin_headers,
        )
        assert filtered.status_code == 200
        filtered_items = filtered.json()["items"]
        assert len(filtered_items) >= 2
        assert all(item["user_id"] == user_id for item in filtered_items)
    finally:
        main_module.settings.gateway_admin_api_key = previous_gateway_admin
        main_module.settings.admin_api_key = previous_admin


def test_gateway_admin_manage_users():
    _clear_faq_table()
    previous_gateway_admin = main_module.settings.gateway_admin_api_key
    previous_admin = main_module.settings.admin_api_key
    main_module.settings.gateway_admin_api_key = "gateway-admin-test-key"
    main_module.settings.admin_api_key = None
    try:
        register = client.post(
            "/gateway/register",
            json={"email": "admin-managed@example.com", "password": "strong-pass-123", "tariff_code": "starter"},
        )
        assert register.status_code == 200
        user_id = register.json()["user_id"]

        admin_headers = {"X-Gateway-Admin-Key": "gateway-admin-test-key"}

        list_resp = client.get("/gateway/admin/users", headers=admin_headers)
        assert list_resp.status_code == 200
        assert list_resp.json()["total_count"] >= 1

        update = client.patch(
            f"/gateway/admin/users/{user_id}",
            headers=admin_headers,
            json={
                "tariff_code": "pro",
                "set_balance_tokens": 12345,
                "balance_reason": "switching to paid plan",
                "is_active": False,
                "regenerate_api_key": True,
            },
        )
        assert update.status_code == 200
        updated = update.json()
        assert updated["tariff_code"] == "pro"
        assert updated["token_balance"] == 12345
        assert updated["is_active"] is False

        usage = client.get(f"/gateway/admin/users/{user_id}/usage", headers=admin_headers)
        assert usage.status_code == 200
        assert isinstance(usage.json()["items"], list)

        unauthorized = client.get("/gateway/admin/users")
        assert unauthorized.status_code == 401
    finally:
        main_module.settings.gateway_admin_api_key = previous_gateway_admin
        main_module.settings.admin_api_key = previous_admin


def test_gateway_provider_requires_configured_key():
    _clear_faq_table()
    main_module.settings.openai_api_key = None
    try:
        register = client.post(
            "/gateway/register",
            json={"email": "provider@example.com", "password": "strong-pass-123"},
        )
        assert register.status_code == 200
        key = register.json()["api_key"]
        headers = {"X-Gateway-Key": key}

        topup = client.post("/gateway/tokens/topup", headers=headers, json={"tokens": 5000})
        assert topup.status_code == 200

        r = client.post(
            "/gateway/generate",
            headers=headers,
            json={"model_id": "proxy/openai-gpt-4o-mini", "prompt": "Привет", "max_tokens": 80},
        )
        assert r.status_code == 502
    finally:
        main_module.settings.openai_api_key = "test-provider-key"


def test_openai_compatible_endpoints():
    _clear_faq_table()
    register = client.post(
        "/gateway/register",
        json={"email": "compat@example.com", "password": "strong-pass-123"},
    )
    assert register.status_code == 200
    api_key = register.json()["api_key"]
    gw_headers = {"X-Gateway-Key": api_key}

    topup = client.post("/gateway/tokens/topup", headers=gw_headers, json={"tokens": 6000})
    assert topup.status_code == 200

    compat_headers = {"Authorization": f"Bearer {api_key}"}
    models_resp = client.get("/v1/models", headers=compat_headers)
    assert models_resp.status_code == 200
    ids = [item["id"] for item in models_resp.json()["data"]]
    assert "local/qwen2.5-3b" in ids

    chat_resp = client.post(
        "/v1/chat/completions",
        headers=compat_headers,
        json={
            "model": "local/qwen2.5-3b",
            "messages": [{"role": "user", "content": "Как защитить API?"}],
            "max_tokens": 120,
        },
    )
    assert chat_resp.status_code == 200
    payload = chat_resp.json()
    assert payload["object"] == "chat.completion"
    assert payload["model"] == "local/qwen2.5-3b"
    assert payload["choices"][0]["message"]["content"]
    assert payload["usage"]["total_tokens"] >= 1

    r_unauthorized = client.get("/v1/models")
    assert r_unauthorized.status_code == 401
