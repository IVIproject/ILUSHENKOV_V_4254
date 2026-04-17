import uuid
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from ollama import Client
from sqlalchemy import func, select
 
from .db import Base, SessionLocal, engine
from .logging_config import get_logger, setup_logging
from .models import RequestLog
from .settings import settings
from .schemas import (
    DomainSuggestionsRequest,
    DomainSuggestionsResponse,
    GenerateRequest,
    GenerateResponse,
    HistoryItem,
    StatsResponse,
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


@app.get("/stats", response_model=StatsResponse)
def stats():
    try:
        with SessionLocal() as db:
            total_requests = db.query(func.count(RequestLog.id)).scalar() or 0
            avg_prompt_length = db.query(func.avg(func.length(RequestLog.prompt))).scalar()
            avg_answer_length = db.query(func.avg(func.length(RequestLog.answer))).scalar()
            day_ago = func.datetime("now", "-1 day")
            requests_last_24h = (
                db.query(func.count(RequestLog.id))
                .filter(RequestLog.created_at >= day_ago)
                .scalar()
            )
        return StatsResponse(
            total_requests=int(total_requests),
            requests_last_24h=int(requests_last_24h or 0),
            average_prompt_length=float(avg_prompt_length or 0.0),
            average_answer_length=float(avg_answer_length or 0.0),
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Stats error: {e}")


@app.post("/generate/domains", response_model=DomainSuggestionsResponse)
def generate_domains(payload: DomainSuggestionsRequest, request: Request):
    prompt = (
        "You are a naming assistant for internet domains.\n"
        f"Generate {payload.count} domain name ideas for business context: "
        f"{payload.business_context}\n"
        f"Keywords: {', '.join(payload.keywords) if payload.keywords else 'none'}\n"
        f"Zone: {payload.zone}\n"
        "Правила:\n"
        "- Только латиница и цифры\n"
        "- Без пробелов\n"
        "- Краткие и запоминающиеся\n"
        "Верни только список по одному домену в строке.\n"
        "Пример:\n"
        "myservice.ru\n"
        "myservice24.ru\n"
    )
    try:
        logger.info(
            "domain generation request received",
            extra={"request_id": request.state.request_id},
        )
        resp = client.chat(
            model=settings.ollama_model,
            messages=[{"role": "user", "content": prompt}],
        )
        raw_text = resp["message"]["content"]
        candidates = []
        for line in raw_text.splitlines():
            cleaned = line.strip().strip("-").strip()
            if not cleaned:
                continue
            if "." not in cleaned:
                continue
            if " " in cleaned:
                continue
            normalized = cleaned.lower()
            if not normalized.endswith(payload.zone):
                continue
            candidates.append(normalized)

        # Keep unique order and cap by requested count.
        unique = list(dict.fromkeys(candidates))[: payload.count]
        if not unique:
            base = "".join(ch for ch in payload.business_context.lower() if ch.isalnum())
            if not base:
                base = "project"
            unique = [f"{base[:12]}{i+1}.{payload.zone}" for i in range(payload.count)]

        with SessionLocal() as db:
            row = RequestLog(prompt=prompt, answer="\n".join(unique))
            db.add(row)
            db.commit()

        return DomainSuggestionsResponse(
            business_context=payload.business_context,
            zone=payload.zone,
            suggestions=unique,
        )
    except Exception as e:
        logger.exception(
            "domain generation failed",
            extra={"request_id": request.state.request_id},
        )
        raise HTTPException(status_code=500, detail=f"Domain generation error: {e}")


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
