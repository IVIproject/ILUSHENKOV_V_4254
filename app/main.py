import uuid
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from ollama import Client
from sqlalchemy import select
 
from .db import Base, SessionLocal, engine
from .logging_config import get_logger, setup_logging
from .models import RequestLog
from .settings import settings
from .schemas import (
    GenerateRequest,
    GenerateResponse,
    HistoryItem,
    StreamChunk,
)
 
setup_logging()
logger = get_logger("app.main")
client = Client(host=settings.ollama_host)


@asynccontextmanager
async def lifespan(_: FastAPI):
    logger.info("application startup")
    Base.metadata.create_all(bind=engine)
    yield
    logger.info("application shutdown")


app = FastAPI(title="ai-servise API", lifespan=lifespan)


@app.middleware("http")
async def add_request_context(request: Request, call_next):
    request_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())
    request.state.request_id = request_id
    response = await call_next(request)
    response.headers["X-Request-ID"] = request_id
    return response
 
 
@app.get("/health")
def health():
    try:
        models = client.list()
        with SessionLocal() as db:
            db.execute(select(1))
        return {
            "status": "ok",
            "ollama_host": settings.ollama_host,
            "model": settings.ollama_model,
            "models_loaded": len(models.get("models", [])),
            "database": "ok",
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Health check error: {e}")
 
 
@app.post("/generate", response_model=GenerateResponse)
def generate(payload: GenerateRequest, request: Request):
    try:
        logger.info(
            "generate request received",
            extra={"request_id": request.state.request_id},
        )
        resp = client.chat(
            model=settings.ollama_model,
            messages=[{"role": "user", "content": payload.prompt}],
        )
        answer = resp["message"]["content"]
 
        with SessionLocal() as db:
            row = RequestLog(prompt=payload.prompt, answer=answer)
            db.add(row)
            db.commit()
 
        return GenerateResponse(answer=answer)
    except Exception as e:
        logger.exception(
            "generation failed",
            extra={"request_id": request.state.request_id},
        )
        raise HTTPException(status_code=500, detail=f"Generation error: {e}")
 
 
@app.get("/history", response_model=list[HistoryItem])
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
            HistoryItem(
                id=r.id,
                prompt=r.prompt,
                answer=r.answer,
                created_at=r.created_at,
            )
            for r in rows
        ]
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"History error: {e}")


@app.post("/generate/stream")
def generate_stream(payload: GenerateRequest, request: Request):
    def iterator():
        try:
            stream = client.chat(
                model=settings.ollama_model,
                messages=[{"role": "user", "content": payload.prompt}],
                stream=True,
            )
            chunks = []
            for part in stream:
                text = part.get("message", {}).get("content", "")
                if not text:
                    continue
                chunks.append(text)
                chunk = StreamChunk(chunk=text)
                yield chunk.model_dump_json() + "\n"

            full_answer = "".join(chunks)
            with SessionLocal() as db:
                row = RequestLog(prompt=payload.prompt, answer=full_answer)
                db.add(row)
                db.commit()
            done_chunk = StreamChunk(chunk="", done=True)
            yield done_chunk.model_dump_json() + "\n"
        except Exception:
            logger.exception(
                "stream generation failed",
                extra={"request_id": request.state.request_id},
            )
            error_chunk = StreamChunk(
                chunk="",
                done=True,
                error="Generation error in stream",
            )
            yield error_chunk.model_dump_json() + "\n"

    return StreamingResponse(iterator(), media_type="application/x-ndjson")
