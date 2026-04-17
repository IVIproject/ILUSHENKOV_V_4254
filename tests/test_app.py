import os

os.environ["DATABASE_URL"] = "sqlite:////tmp/ai_servise_test.db"
os.environ["OLLAMA_HOST"] = "http://fake-ollama"
os.environ["OLLAMA_MODEL"] = "qwen2.5:3b"

from fastapi.testclient import TestClient
import app.main as main_module
from app.db import Base, engine

class FakeClient:
    def list(self):
        return {"models": [{"name": "qwen2.5:3b"}]}

    def chat(self, model, messages):
        return {"message": {"content": f"fake answer for: {messages[0]['content']}"}}

main_module.client = FakeClient()
Base.metadata.create_all(bind=engine)

client = TestClient(main_module.app)

def test_health():
    r = client.get("/health")
    assert r.status_code == 200
    data = r.json()
    assert data["status"] == "ok"
    assert data["database"] == "ok"

def test_generate_and_history():
    r = client.post("/generate", json={"prompt": "hello"})
    assert r.status_code == 200
    assert "answer" in r.json()

    h = client.get("/history?limit=1")
    assert h.status_code == 200
    assert isinstance(h.json(), list)
