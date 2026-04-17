import os
from fastapi import FastAPI, HTTPException, Query
from dotenv import load_dotenv
from ollama import Client
from sqlalchemy import select
from .db import Base, SessionLocal, engine
from .models import RequestLog
 
load_dotenv()
 
OLLAMA_HOST = os.getenv("OLLAMA_HOST", "http://127.0.0.1:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "qwen2.5:3b")
 
client = Client(host=OLLAMA_HOST)
app = FastAPI(title="ai-servise API")
 
@app.on_event("startup")
def on_startup():
    Base.metadata.create_all(bind=engine)
 
@app.get("/health")
def health():
    try:
        models = client.list()
        db_ok = True
        with SessionLocal() as db:
            db.execute(select(1))
        return {
            "status": "ok",
            "ollama_host": OLLAMA_HOST,
            "model": OLLAMA_MODEL,
            "models_loaded": len(models.get("models", [])),
            "database": "ok" if db_ok else "error",
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Health check error: {e}")
 
@app.get("/generate")
def generate(prompt: str = Query(..., min_length=1, max_length=2000)):
    try:
        resp = client.chat(
            model=OLLAMA_MODEL,
            messages=[{"role": "user", "content": prompt}],
        )
        answer = resp["message"]["content"]
 
        with SessionLocal() as db:
            row = RequestLog(prompt=prompt, answer=answer)
            db.add(row)
            db.commit()
 
        return {"answer": answer}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Generation error: {e}")
 
@app.get("/history")
def history(limit: int = Query(10, ge=1, le=100)):
    try:
        with SessionLocal() as db:
            rows = (
                db.query(RequestLog)
                .order_by(RequestLog.id.desc())
                .limit(limit)
                .all()
            )
 
        return [
            {
                "id": r.id,
                "prompt": r.prompt,
                "answer": r.answer,
                "created_at": str(r.created_at),
            }
            for r in rows
        ]
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"History error: {e}")
