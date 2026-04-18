import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from ollama import Client
from sqlalchemy import func, select

from .db import Base, SessionLocal, engine
from .logging_config import get_logger, setup_logging
from .models import RequestLog, SupportFaqEntry
from .schemas import (
    DomainSuggestionsRequest,
    DomainSuggestionsResponse,
    GenerateRequest,
    GenerateResponse,
    HistoryItem,
    ModeRunRequest,
    ModeRunResponse,
    PageTemplateGenerateRequest,
    StatsResponse,
    StreamChunk,
    SupportFaqAskRequest,
    SupportFaqAskResponse,
    SupportFaqImportRequest,
    SupportFaqImportResponse,
)
from .services import (
    extract_domain_suggestions,
    render_php_template,
    run_chat_mode,
    run_domain_mode,
    run_support_faq_mode,
)
from .page_templates import (
    build_hosting_template_from_source,
    generate_hosting_page_from_template,
)
from .settings import settings

setup_logging()
logger = get_logger("app.main")
client = Client(host=settings.ollama_host)


def _save_log(prompt: str, answer: str) -> None:
    with SessionLocal() as db:
        db.add(RequestLog(prompt=prompt, answer=answer))
        db.commit()


def _resolve_template_path(template_name: str) -> Path:
    safe = template_name.replace("\\", "/").split("/")[-1].strip()
    if not safe:
        raise HTTPException(status_code=400, detail="template_name is required")
    if not safe.endswith(".php"):
        safe += ".php"
    if not all(ch.isalnum() or ch in "._-" for ch in safe):
        raise HTTPException(status_code=400, detail="Invalid template_name")
    template_path = Path("templates/pages") / safe
    if not template_path.exists() or not template_path.is_file():
        raise HTTPException(status_code=404, detail=f"Template not found: {safe}")
    return template_path


def _generate_php_from_template_name(template_name: str, content_prompt: str) -> tuple[str, str]:
    template_path = _resolve_template_path(template_name)
    template_text = template_path.read_text(encoding="utf-8")
    generated_php = generate_hosting_page_from_template(
        client=client,
        model=settings.ollama_model,
        template_text=template_text,
        content_prompt=content_prompt,
    )
    output_name = f"{template_path.stem}-generated.php"
    return generated_php, output_name


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
        answer = run_chat_mode(
            client=client,
            model=settings.ollama_model,
            prompt=payload.prompt,
        )
        _save_log(prompt=payload.prompt, answer=answer)
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
                id=row.id,
                prompt=row.prompt,
                answer=row.answer,
                created_at=row.created_at,
            )
            for row in rows
        ]
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"History error: {e}")


@app.get("/stats", response_model=StatsResponse)
def stats():
    try:
        day_ago = datetime.now(timezone.utc) - timedelta(days=1)
        with SessionLocal() as db:
            total_requests = db.query(func.count(RequestLog.id)).scalar() or 0
            avg_prompt_length = db.query(func.avg(func.length(RequestLog.prompt))).scalar()
            avg_answer_length = db.query(func.avg(func.length(RequestLog.answer))).scalar()
            requests_last_24h = (
                db.query(func.count(RequestLog.id))
                .filter(RequestLog.created_at >= day_ago)
                .scalar()
            )
            latest = (
                db.query(RequestLog.created_at)
                .order_by(RequestLog.created_at.desc())
                .limit(1)
                .scalar()
            )
        return StatsResponse(
            total_requests=int(total_requests),
            requests_last_24h=int(requests_last_24h or 0),
            average_prompt_length=float(avg_prompt_length or 0.0),
            average_answer_length=float(avg_answer_length or 0.0),
            latest_request_at=latest,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Stats error: {e}")


@app.post("/generate/domains", response_model=DomainSuggestionsResponse)
def generate_domains(payload: DomainSuggestionsRequest, request: Request):
    try:
        logger.info(
            "domain generation request received",
            extra={"request_id": request.state.request_id},
        )
        raw = run_domain_mode(
            client=client,
            model=settings.ollama_model,
            business_context=payload.business_context,
            keywords=payload.keywords,
            zone=payload.zone,
            count=payload.count,
        )
        suggestions = extract_domain_suggestions(raw, payload.zone, payload.count)
        if len(suggestions) < payload.count:
            base = "".join(ch for ch in payload.business_context.lower() if ch.isalnum()) or "project"
            while len(suggestions) < payload.count:
                suggestions.append(f"{base[:12]}{len(suggestions)+1}{payload.zone}")
        _save_log(prompt=payload.business_context, answer="\n".join(suggestions))
        return DomainSuggestionsResponse(
            business_context=payload.business_context,
            zone=payload.zone,
            suggestions=suggestions,
        )
    except Exception as e:
        logger.exception(
            "domain generation failed",
            extra={"request_id": request.state.request_id},
        )
        raise HTTPException(status_code=500, detail=f"Domain generation error: {e}")


@app.post("/support/faq/import", response_model=SupportFaqImportResponse)
def import_support_faq(payload: SupportFaqImportRequest):
    try:
        imported = 0
        with SessionLocal() as db:
            for item in payload.items:
                exists = (
                    db.query(SupportFaqEntry)
                    .filter(
                        SupportFaqEntry.question == item.question.strip(),
                        SupportFaqEntry.answer == item.answer.strip(),
                    )
                    .first()
                )
                if exists:
                    continue
                db.add(
                    SupportFaqEntry(
                        question=item.question.strip(),
                        answer=item.answer.strip(),
                        source=item.source,
                    )
                )
                imported += 1
            db.commit()
        return SupportFaqImportResponse(imported=imported)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"FAQ import error: {e}")


@app.post("/support/faq/ask", response_model=SupportFaqAskResponse)
def ask_support_faq(payload: SupportFaqAskRequest):
    try:
        with SessionLocal() as db:
            rows = (
                db.query(SupportFaqEntry)
                .order_by(SupportFaqEntry.id.desc())
                .limit(payload.max_context_items)
                .all()
            )
        answer = run_support_faq_mode(
            client=client,
            model=settings.ollama_model,
            user_question=payload.question,
            faq_pairs=[(row.question, row.answer) for row in rows],
        )
        _save_log(prompt=payload.question, answer=answer)
        return SupportFaqAskResponse(answer=answer, matched_items=len(rows))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Support FAQ ask error: {e}")


@app.post("/page-template/generate-file")
def generate_page_from_template(payload: PageTemplateGenerateRequest):
    try:
        generated_php, output_name = _generate_php_from_template_name(
            template_name=payload.template_name,
            content_prompt=payload.content_prompt,
        )
        if payload.output_filename:
            output_name = payload.output_filename
        if not output_name.endswith(".php"):
            output_name += ".php"
        return StreamingResponse(
            iter([generated_php.encode("utf-8")]),
            media_type="application/x-httpd-php",
            headers={
                "Content-Disposition": f'attachment; filename="{output_name}"',
            },
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Template generation error: {e}")


@app.post("/page-template/prepare-hosting")
def prepare_hosting_template():
    try:
        source = Path("hosting.php")
        if not source.exists():
            raise HTTPException(status_code=404, detail="hosting.php not found")
        template_dir = Path("templates/pages")
        template_dir.mkdir(parents=True, exist_ok=True)
        output = template_dir / "hosting.template.php"
        content = source.read_text(encoding="utf-8")
        template_text = build_hosting_template_from_source(content)
        output.write_text(template_text, encoding="utf-8")
        return {
            "prepared": True,
            "template_path": str(output),
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Template prepare error: {e}")


@app.post("/mode/run", response_model=ModeRunResponse)
def run_mode(payload: ModeRunRequest, request: Request):
    try:
        mode = payload.mode.strip()
        data = payload.payload or {}

        if mode == "chat":
            prompt = str(data.get("prompt", "")).strip()
            if not prompt:
                raise HTTPException(status_code=400, detail="payload.prompt is required for chat mode")
            answer = run_chat_mode(client=client, model=settings.ollama_model, prompt=prompt)
            _save_log(prompt=prompt, answer=answer)
            return ModeRunResponse(mode=mode, result={"text": answer})

        if mode == "domains":
            business_context = str(data.get("business_context", "")).strip()
            if not business_context:
                raise HTTPException(status_code=400, detail="payload.business_context is required for domains mode")
            zone = str(data.get("zone", ".ru"))
            count = int(data.get("count", 10))
            keywords = data.get("keywords", [])
            if not isinstance(keywords, list):
                keywords = []
            raw = run_domain_mode(
                client=client,
                model=settings.ollama_model,
                business_context=business_context,
                keywords=[str(k) for k in keywords],
                zone=zone,
                count=count,
            )
            suggestions = extract_domain_suggestions(raw, zone, count)
            if len(suggestions) < count:
                base = "".join(ch for ch in business_context.lower() if ch.isalnum()) or "project"
                while len(suggestions) < count:
                    suggestions.append(f"{base[:12]}{len(suggestions)+1}{zone}")
            _save_log(prompt=business_context, answer="\n".join(suggestions))
            return ModeRunResponse(mode=mode, result={"suggestions": suggestions, "zone": zone})

        if mode == "php_page":
            template_name = str(data.get("template_name", "")).strip()
            template_html = str(data.get("template_html", ""))
            content_prompt = str(data.get("content_prompt", "")).strip()
            if not content_prompt:
                raise HTTPException(
                    status_code=400,
                    detail="payload.content_prompt is required for php_page mode",
                )
            if template_name:
                rendered, output_name = _generate_php_from_template_name(
                    template_name=template_name,
                    content_prompt=content_prompt,
                )
                _save_log(prompt=content_prompt, answer=rendered)
                return ModeRunResponse(
                    mode=mode,
                    result={
                        "php_page": rendered,
                        "template_name": template_name,
                        "output_filename": output_name,
                    },
                )

            if not template_html:
                raise HTTPException(
                    status_code=400,
                    detail="payload.template_name or payload.template_html is required for php_page mode",
                )

            rendered = render_php_template(
                client=client,
                model=settings.ollama_model,
                template_html=template_html,
                prompt=content_prompt,
            )
            _save_log(prompt=content_prompt, answer=rendered)
            return ModeRunResponse(mode=mode, result={"php_page": rendered})

        if mode == "support_faq":
            question = str(data.get("question", "")).strip()
            max_context_items = int(data.get("max_context_items", 5))
            if not question:
                raise HTTPException(status_code=400, detail="payload.question is required for support_faq mode")
            with SessionLocal() as db:
                rows = (
                    db.query(SupportFaqEntry)
                    .order_by(SupportFaqEntry.id.desc())
                    .limit(max(1, min(max_context_items, 20)))
                    .all()
                )
            answer = run_support_faq_mode(
                client=client,
                model=settings.ollama_model,
                user_question=question,
                faq_pairs=[(row.question, row.answer) for row in rows],
            )
            _save_log(prompt=question, answer=answer)
            return ModeRunResponse(
                mode=mode,
                result={"answer": answer, "matched_items": len(rows)},
            )

        raise HTTPException(status_code=400, detail=f"Unsupported mode: {mode}")
    except HTTPException:
        raise
    except Exception as e:
        logger.exception(
            "mode run failed",
            extra={"request_id": request.state.request_id},
        )
        raise HTTPException(status_code=500, detail=f"Mode run error: {e}")


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
                yield StreamChunk(chunk=text).model_dump_json() + "\n"

            full_answer = "".join(chunks)
            _save_log(prompt=payload.prompt, answer=full_answer)
            yield StreamChunk(chunk="", done=True).model_dump_json() + "\n"
        except Exception:
            logger.exception(
                "stream generation failed",
                extra={"request_id": request.state.request_id},
            )
            yield StreamChunk(chunk="", done=True, error="Generation error in stream").model_dump_json() + "\n"

    return StreamingResponse(iterator(), media_type="application/x-ndjson")
