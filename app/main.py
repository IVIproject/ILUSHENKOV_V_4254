import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, StreamingResponse
from ollama import Client
from sqlalchemy import desc, func, select

from .db import Base, SessionLocal, engine
from .gateway_services import (
    call_openai_proxy,
    compute_token_charge,
    estimate_messages_tokens,
    estimate_text_tokens,
    generate_api_key,
    get_gateway_models,
    get_tariff_plans,
    hash_password,
    normalize_email,
    resolve_gateway_model,
)
from .logging_config import get_logger, setup_logging
from .models import (
    GatewayModel,
    GatewayUsageLog,
    GatewayUser,
    RequestLog,
    SupportFaqEntry,
    SupportFaqQueryMetric,
)
from .schemas import (
    DomainSuggestionsRequest,
    DomainSuggestionsResponse,
    GatewayBalanceResponse,
    GatewayCatalogResponse,
    GatewayGenerateRequest,
    GatewayGenerateResponse,
    GatewayModelItem,
    GatewayTariffItem,
    GatewayTariffsResponse,
    GatewayTopUpRequest,
    GatewayTopUpResponse,
    GatewayUserRegisterRequest,
    GatewayUserResponse,
    GenerateRequest,
    GenerateResponse,
    HistoryItem,
    ModeRunRequest,
    ModeRunResponse,
    PageTemplateGenerateRequest,
    StatsResponse,
    StreamChunk,
    SupportDialogsImportRequest,
    SupportDialogsImportResponse,
    SupportFaqAskRequest,
    SupportFaqAskResponse,
    SupportFaqImportRequest,
    SupportFaqImportResponse,
)
from .services import (
    extract_support_faq_pairs,
    extract_domain_suggestions,
    run_chat_mode,
    run_domain_mode,
    run_support_faq_mode,
    select_relevant_faq_pairs,
    normalize_text_for_metric,
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


def _save_support_quality_log(
    *,
    question: str,
    matched_items: int,
    relevance_avg: float,
    relevance_max: float,
    zero_match: bool,
    source_mode: str,
) -> None:
    normalized = normalize_text_for_metric(question)
    with SessionLocal() as db:
        db.add(
            SupportFaqQueryMetric(
                question=question,
                normalized_question=normalized,
                matched_items=matched_items,
                relevance_avg=relevance_avg,
                relevance_max=relevance_max,
                zero_match=zero_match,
                source_mode=source_mode,
            )
        )
        db.commit()


def _verify_admin_api_key(
    api_key: str | None = Header(default=None, alias="X-API-Key"),
) -> None:
    if not settings.admin_api_key:
        return
    if not api_key or api_key != settings.admin_api_key:
        raise HTTPException(status_code=401, detail="Invalid or missing X-API-Key")


def _get_gateway_user(gateway_key: str | None = Header(default=None, alias="X-Gateway-Key")) -> GatewayUser:
    if not gateway_key:
        raise HTTPException(status_code=401, detail="X-Gateway-Key header is required")
    with SessionLocal() as db:
        user = (
            db.query(GatewayUser)
            .filter(GatewayUser.api_key == gateway_key.strip(), GatewayUser.is_active.is_(True))
            .first()
        )
    if not user:
        raise HTTPException(status_code=401, detail="Invalid gateway key")
    return user


def _get_gateway_user_from_bearer(authorization: str | None = Header(default=None, alias="Authorization")) -> GatewayUser:
    if not authorization:
        raise HTTPException(status_code=401, detail="Authorization header is required")
    prefix = "Bearer "
    if not authorization.startswith(prefix):
        raise HTTPException(status_code=401, detail="Authorization must use Bearer token")
    token = authorization[len(prefix) :].strip()
    if not token:
        raise HTTPException(status_code=401, detail="Bearer token is empty")
    return _get_gateway_user(token)


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

            total_support_questions = db.query(func.count(SupportFaqQueryMetric.id)).scalar() or 0
            zero_match_count = (
                db.query(func.count(SupportFaqQueryMetric.id))
                .filter(SupportFaqQueryMetric.zero_match.is_(True))
                .scalar()
                or 0
            )
            avg_relevance = db.query(func.avg(SupportFaqQueryMetric.relevance_avg)).scalar()

            top_rows = (
                db.query(
                    SupportFaqQueryMetric.normalized_question,
                    func.count(SupportFaqQueryMetric.id).label("cnt"),
                )
                .group_by(SupportFaqQueryMetric.normalized_question)
                .order_by(desc("cnt"))
                .limit(5)
                .all()
            )
            top_questions = [row[0] for row in top_rows if row[0]]

        no_match_rate = (float(zero_match_count) / float(total_support_questions)) if total_support_questions else 0.0
        return StatsResponse(
            total_requests=int(total_requests),
            requests_last_24h=int(requests_last_24h or 0),
            average_prompt_length=float(avg_prompt_length or 0.0),
            average_answer_length=float(avg_answer_length or 0.0),
            latest_request_at=latest,
            support_faq_total_requests=int(total_support_questions),
            support_faq_zero_match_total=int(zero_match_count),
            support_faq_no_match_rate=float(no_match_rate),
            support_faq_avg_relevance_score=float(avg_relevance or 0.0),
            support_faq_top_questions=top_questions,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Stats error: {e}")


@app.get("/gateway", response_class=HTMLResponse)
def gateway_landing_page():
    page = Path("templates/gateway/index.html")
    if not page.exists():
        raise HTTPException(status_code=404, detail="Gateway page not found")
    return page.read_text(encoding="utf-8")


@app.get("/gateway/tariffs", response_model=GatewayTariffsResponse)
def gateway_tariffs():
    tariffs = get_tariff_plans()
    return GatewayTariffsResponse(
        tariffs=[
            GatewayTariffItem(
                code=item.code,
                name=item.name,
                monthly_price_rub=item.price_rub,
                included_tokens=item.tokens,
                overage_price_per_1k_tokens_rub=round(item.price_rub / max(1, item.tokens / 1000), 2),
                features=[
                    "API key access",
                    "Local model routing",
                    "Provider proxy support",
                    item.description,
                ],
            )
            for item in tariffs
        ]
    )


@app.post("/gateway/register", response_model=GatewayUserResponse)
def gateway_register(payload: GatewayUserRegisterRequest):
    email = normalize_email(payload.email)
    plans = {plan.code: plan for plan in get_tariff_plans()}
    plan = plans.get(payload.tariff_code)
    if not plan:
        raise HTTPException(status_code=400, detail=f"Unsupported tariff_code: {payload.tariff_code}")

    _, password_hash = hash_password(payload.password)
    api_key, _, _, _ = generate_api_key()
    with SessionLocal() as db:
        exists = db.query(GatewayUser).filter(GatewayUser.email == email).first()
        if exists:
            raise HTTPException(status_code=409, detail="Email already registered")
        user = GatewayUser(
            email=email,
            password_hash=password_hash,
            api_key=api_key,
            tokens_balance=0,
            plan=plan.code,
            is_active=True,
        )
        db.add(user)
        db.commit()
        db.refresh(user)
        return GatewayUserResponse(
            user_id=user.id,
            email=user.email,
            api_key=user.api_key,
            token_balance=user.tokens_balance,
            tariff_code=user.plan,
        )


@app.get("/gateway/models", response_model=GatewayCatalogResponse)
def gateway_models(_: GatewayUser = Depends(_get_gateway_user)):
    with SessionLocal() as db:
        rows = db.query(GatewayModel).filter(GatewayModel.is_active.is_(True)).order_by(GatewayModel.id.asc()).all()
    if not rows:
        catalog = get_gateway_models()
        return GatewayCatalogResponse(
            models=[
                GatewayModelItem(
                    model_id=m.model_id,
                    display_name=m.label,
                    provider=m.provider,
                    target_model=m.upstream_model,
                    price_per_1k_tokens=float(m.cost_per_1k_tokens),
                    is_active=True,
                )
                for m in catalog
            ]
        )
    return GatewayCatalogResponse(
        models=[
            GatewayModelItem(
                model_id=row.model_key,
                display_name=row.display_name,
                provider=row.provider,
                target_model=row.target_model,
                price_per_1k_tokens=row.price_per_1k_tokens,
                is_active=row.is_active,
            )
            for row in rows
        ]
    )


@app.get("/gateway/balance", response_model=GatewayBalanceResponse)
def gateway_balance(user: GatewayUser = Depends(_get_gateway_user)):
    return GatewayBalanceResponse(
        user_id=user.id,
        token_balance=user.tokens_balance,
        tariff_code=user.plan,
    )


@app.post("/gateway/tokens/topup", response_model=GatewayTopUpResponse)
def gateway_tokens_topup(payload: GatewayTopUpRequest, user: GatewayUser = Depends(_get_gateway_user)):
    with SessionLocal() as db:
        row = db.query(GatewayUser).filter(GatewayUser.id == user.id).first()
        if not row:
            raise HTTPException(status_code=404, detail="Gateway user not found")
        row.tokens_balance += payload.tokens
        db.commit()
        db.refresh(row)
        return GatewayTopUpResponse(user_id=row.id, token_balance=row.tokens_balance)


@app.post("/gateway/generate", response_model=GatewayGenerateResponse)
def gateway_generate(payload: GatewayGenerateRequest, user: GatewayUser = Depends(_get_gateway_user)):
    model_def = resolve_gateway_model(payload.model_id)
    if not model_def:
        raise HTTPException(status_code=404, detail=f"Unknown model_id: {payload.model_id}")

    prompt = payload.prompt.strip()
    if not prompt:
        raise HTTPException(status_code=400, detail="prompt is required")
    messages = [{"role": "user", "content": prompt}]

    with SessionLocal() as db:
        user_row = db.query(GatewayUser).filter(GatewayUser.id == user.id, GatewayUser.is_active.is_(True)).first()
        if not user_row:
            raise HTTPException(status_code=401, detail="Gateway user inactive")

        try:
            if model_def.provider == "ollama":
                content = run_chat_mode(client=client, model=model_def.upstream_model, prompt=prompt)
                prompt_tokens = estimate_messages_tokens(messages)
                completion_tokens = estimate_text_tokens(content)
                total_tokens = prompt_tokens + completion_tokens
            elif model_def.provider == "openai":
                content, prompt_tokens, completion_tokens, total_tokens = call_openai_proxy(
                    model=model_def.upstream_model,
                    messages=messages,
                    temperature=payload.temperature,
                    max_tokens=payload.max_tokens,
                )
            else:
                raise RuntimeError(f"Unsupported provider: {model_def.provider}")

            cost_tokens = compute_token_charge(total_tokens, model_def.cost_per_1k_tokens)
            if user_row.tokens_balance < cost_tokens:
                raise HTTPException(
                    status_code=402,
                    detail=(
                        f"Insufficient token balance. Need {cost_tokens}, "
                        f"available {user_row.tokens_balance}"
                    ),
                )

            user_row.tokens_balance -= cost_tokens
            db.add(
                GatewayUsageLog(
                    user_id=user_row.id,
                    model_key=model_def.model_id,
                    provider=model_def.provider,
                    prompt_tokens=prompt_tokens,
                    completion_tokens=completion_tokens,
                    total_tokens=total_tokens,
                    cost_tokens=cost_tokens,
                    success=True,
                )
            )
            db.commit()
            db.refresh(user_row)

            return GatewayGenerateResponse(
                provider=model_def.provider,
                model_id=model_def.model_id,
                answer=content,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                total_tokens=total_tokens,
                tokens_spent=cost_tokens,
                token_balance=user_row.tokens_balance,
            )
        except HTTPException:
            raise
        except Exception as exc:
            db.add(
                GatewayUsageLog(
                    user_id=user_row.id,
                    model_key=model_def.model_id,
                    provider=model_def.provider,
                    prompt_tokens=0,
                    completion_tokens=0,
                    total_tokens=0,
                    cost_tokens=0,
                    success=False,
                    error_message=str(exc),
                )
            )
            db.commit()
            raise HTTPException(status_code=502, detail=f"Gateway provider error: {exc}")


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
def import_support_faq(
    payload: SupportFaqImportRequest,
    _: None = Depends(_verify_admin_api_key),
):
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


@app.post("/support/dialogs/import", response_model=SupportDialogsImportResponse)
def import_support_dialogs(
    payload: SupportDialogsImportRequest,
    _: None = Depends(_verify_admin_api_key),
):
    try:
        pairs = extract_support_faq_pairs(payload.transcript)
        if not pairs:
            return SupportDialogsImportResponse(imported=0, parsed_pairs=0)

        imported = 0
        with SessionLocal() as db:
            for question, answer in pairs:
                q = question.strip()
                a = answer.strip()
                if not q or not a:
                    continue
                exists = (
                    db.query(SupportFaqEntry)
                    .filter(
                        SupportFaqEntry.question == q,
                        SupportFaqEntry.answer == a,
                    )
                    .first()
                )
                if exists:
                    continue
                db.add(
                    SupportFaqEntry(
                        question=q,
                        answer=a,
                        source="support_dialog",
                    )
                )
                imported += 1
            db.commit()

        return SupportDialogsImportResponse(imported=imported, parsed_pairs=len(pairs))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Dialogs import error: {e}")


@app.post("/support/faq/ask", response_model=SupportFaqAskResponse)
def ask_support_faq(payload: SupportFaqAskRequest):
    try:
        max_items = max(1, min(payload.max_context_items, 20))
        with SessionLocal() as db:
            rows = (
                db.query(SupportFaqEntry)
                .order_by(SupportFaqEntry.id.desc())
                .limit(200)
                .all()
            )
        selected_pairs = select_relevant_faq_pairs(
            user_question=payload.question,
            faq_pairs=[(row.question, row.answer) for row in rows],
            max_items=max_items,
        )
        scores = [item.score for item in selected_pairs]
        relevance_avg = (sum(scores) / len(scores)) if scores else 0.0
        relevance_max = max(scores) if scores else 0.0
        zero_match = relevance_max <= 0
        answer = run_support_faq_mode(
            client=client,
            model=settings.ollama_model,
            user_question=payload.question,
            faq_pairs=[item.pair for item in selected_pairs],
        )
        _save_log(prompt=payload.question, answer=answer)
        _save_support_quality_log(
            question=payload.question,
            matched_items=len(selected_pairs),
            relevance_avg=float(relevance_avg),
            relevance_max=float(relevance_max),
            zero_match=zero_match,
            source_mode="support_faq",
        )
        return SupportFaqAskResponse(answer=answer, matched_items=len(selected_pairs))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Support FAQ ask error: {e}")


@app.post("/page-template/generate-file")
def generate_page_from_template(payload: PageTemplateGenerateRequest):
    try:
        template_path = _resolve_template_path(payload.template_name)
        template_text = template_path.read_text(encoding="utf-8")
        generated_php = generate_hosting_page_from_template(
            client=client,
            model=settings.ollama_model,
            template_text=template_text,
            content_prompt=payload.content_prompt,
        )
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
            raise HTTPException(
                status_code=400,
                detail=(
                    "php_page mode is disabled. "
                    "Use POST /page-template/generate-file for file output."
                ),
            )

        if mode == "support_faq":
            question = str(data.get("question", "")).strip()
            max_context_items = int(data.get("max_context_items", 5))
            if not question:
                raise HTTPException(status_code=400, detail="payload.question is required for support_faq mode")
            safe_context_items = max(1, min(max_context_items, 20))
            with SessionLocal() as db:
                rows = (
                    db.query(SupportFaqEntry)
                    .order_by(SupportFaqEntry.id.desc())
                    .limit(200)
                    .all()
                )
            selected_pairs = select_relevant_faq_pairs(
                user_question=question,
                faq_pairs=[(row.question, row.answer) for row in rows],
                max_items=safe_context_items,
            )
            scores = [item.score for item in selected_pairs]
            relevance_avg = (sum(scores) / len(scores)) if scores else 0.0
            relevance_max = max(scores) if scores else 0.0
            zero_match = relevance_max <= 0
            answer = run_support_faq_mode(
                client=client,
                model=settings.ollama_model,
                user_question=question,
                faq_pairs=[item.pair for item in selected_pairs],
            )
            _save_log(prompt=question, answer=answer)
            _save_support_quality_log(
                question=question,
                matched_items=len(selected_pairs),
                relevance_avg=float(relevance_avg),
                relevance_max=float(relevance_max),
                zero_match=zero_match,
                source_mode="mode_run",
            )
            return ModeRunResponse(
                mode=mode,
                result={"answer": answer, "matched_items": len(selected_pairs)},
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
