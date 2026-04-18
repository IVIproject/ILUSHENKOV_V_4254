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
    hash_password,
    normalize_email,
    verify_password,
)
from .logging_config import get_logger, setup_logging
from .models import (
    GatewayBalanceAuditLog,
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
    GatewayAdminModelCreateRequest,
    GatewayAdminModelUpdateRequest,
    GatewayAdminModelCreateRequest,
    GatewayAdminUserItem,
    GatewayAdminUserUpdateRequest,
    GatewayAdminUsersResponse,
    GatewayBalanceAuditItem,
    GatewayBalanceAuditResponse,
    GatewayBalanceResponse,
    GatewayCatalogResponse,
    GatewayChatRequest,
    GatewayChatResponse,
    GatewayGenerateRequest,
    GatewayGenerateResponse,
    GatewayEstimateCostRequest,
    GatewayEstimateCostResponse,
    GatewayLoginRequest,
    GatewayMeResponse,
    GatewayModelItem,
    GatewayTopUpRequest,
    GatewayTopUpResponse,
    GatewayUsageLogItem,
    GatewayUsageLogsResponse,
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


def _admin_emails_set() -> set[str]:
    raw = settings.gateway_admin_emails.strip()
    if not raw:
        return set()
    return {normalize_email(item) for item in raw.split(",") if item.strip()}


def _is_admin_email(email: str) -> bool:
    return normalize_email(email) in _admin_emails_set()


def _is_admin_user(user: GatewayUser) -> bool:
    if not user.is_active:
        return False
    if user.role == "admin":
        return True
    return _is_admin_email(user.email)


def _effective_model_price_per_1k(row: GatewayModel) -> float:
    if row.external_price_per_1k_tokens is not None:
        return float(row.external_price_per_1k_tokens) * (1.0 + float(row.markup_percent) / 100.0)
    return float(row.price_per_1k_tokens)


def _model_item_from_row(row: GatewayModel) -> GatewayModelItem:
    return GatewayModelItem(
        model_id=row.model_key,
        display_name=row.display_name,
        provider=row.provider,
        target_model=row.target_model,
        price_per_1k_tokens=round(_effective_model_price_per_1k(row), 6),
        external_price_per_1k_tokens=row.external_price_per_1k_tokens,
        markup_percent=float(row.markup_percent or 0.0),
        is_active=row.is_active,
    )


def _ensure_catalog_seeded(db) -> None:
    existing = db.query(GatewayModel.id).limit(1).first()
    if existing:
        return
    for model in get_gateway_models():
        db.add(
            GatewayModel(
                model_key=model.model_id,
                display_name=model.label,
                provider=model.provider,
                target_model=model.upstream_model,
                price_per_1k_tokens=float(model.cost_per_1k_tokens),
                external_price_per_1k_tokens=(
                    float(model.cost_per_1k_tokens) if model.provider == "openai" else None
                ),
                markup_percent=15.0 if model.provider == "openai" else 0.0,
                is_active=True,
            )
        )
    db.commit()


def _resolve_model_for_request(db, model_id: str) -> GatewayModel:
    normalized = model_id.strip().lower()
    row = (
        db.query(GatewayModel)
        .filter(
            func.lower(GatewayModel.model_key) == normalized,
            GatewayModel.is_active.is_(True),
        )
        .first()
    )
    if row:
        return row

    row = (
        db.query(GatewayModel)
        .filter(
            func.lower(GatewayModel.target_model) == normalized,
            GatewayModel.is_active.is_(True),
        )
        .first()
    )
    if row:
        return row

    row = (
        db.query(GatewayModel)
        .filter(
            func.lower(GatewayModel.display_name) == normalized,
            GatewayModel.is_active.is_(True),
        )
        .first()
    )
    if row:
        return row

    raise HTTPException(status_code=404, detail=f"Unknown model_id: {model_id}")


def _charge_for_model(total_tokens: int, model_row: GatewayModel) -> int:
    return compute_token_charge(total_tokens, _effective_model_price_per_1k(model_row))


def _estimate_charge_for_prompt(prompt: str, price_per_1k_tokens: float) -> tuple[int, int, int]:
    prompt_tokens = estimate_text_tokens(prompt)
    # Conservative preview: estimate output roughly at 60% of input
    completion_tokens = max(32, int(round(prompt_tokens * 0.6)))
    total_tokens = prompt_tokens + completion_tokens
    estimated_charge = compute_token_charge(total_tokens, max(0.0, price_per_1k_tokens))
    return prompt_tokens, completion_tokens, estimated_charge


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


def _verify_gateway_admin_key(user: GatewayUser = Depends(_get_gateway_user)) -> GatewayUser:
    if not _is_admin_user(user):
        raise HTTPException(status_code=403, detail="Admin role required")
    return user


def _verify_gateway_user_password(user: GatewayUser, password: str) -> bool:
    if not user.password_hash:
        return False
    parts = user.password_hash.split("$", 1)
    if len(parts) != 2:
        return False
    salt, digest = parts
    if not salt or not digest:
        return False
    return verify_password(password, salt, digest)


def _log_balance_audit(
    *,
    db,
    user_id: int,
    action: str,
    delta_tokens: int,
    balance_before: int,
    balance_after: int,
    actor: str,
    actor_reference: str | None = None,
    reason: str | None = None,
) -> None:
    db.add(
        GatewayBalanceAuditLog(
            user_id=user_id,
            action=action,
            delta_tokens=delta_tokens,
            balance_before=balance_before,
            balance_after=balance_after,
            actor=actor,
            actor_reference=actor_reference,
            reason=reason,
        )
    )


def _to_balance_audit_item(row: GatewayBalanceAuditLog) -> GatewayBalanceAuditItem:
    return GatewayBalanceAuditItem(
        id=row.id,
        user_id=row.user_id,
        action=row.action,
        delta_tokens=row.delta_tokens,
        balance_before=row.balance_before,
        balance_after=row.balance_after,
        actor=row.actor,
        actor_reference=row.actor_reference,
        reason=row.reason,
        created_at=row.created_at,
    )


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


@app.get("/gateway/profile", response_class=HTMLResponse)
def gateway_profile_page():
    page = Path("templates/gateway/profile.html")
    if not page.exists():
        raise HTTPException(status_code=404, detail="Gateway profile page not found")
    return page.read_text(encoding="utf-8")


@app.get("/gateway/register", response_class=HTMLResponse)
def gateway_register_page():
    page = Path("templates/gateway/register.html")
    if not page.exists():
        raise HTTPException(status_code=404, detail="Gateway register page not found")
    return page.read_text(encoding="utf-8")


@app.get("/gateway/login", response_class=HTMLResponse)
def gateway_login_page():
    page = Path("templates/gateway/login.html")
    if not page.exists():
        raise HTTPException(status_code=404, detail="Gateway login page not found")
    return page.read_text(encoding="utf-8")


@app.get("/gateway/models/page", response_class=HTMLResponse)
def gateway_models_page():
    page = Path("templates/gateway/models.html")
    if not page.exists():
        raise HTTPException(status_code=404, detail="Gateway models page not found")
    return page.read_text(encoding="utf-8")


@app.get("/gateway/model/{model_id:path}", response_class=HTMLResponse)
def gateway_model_detail_page(model_id: str):
    page = Path("templates/gateway/model-detail.html")
    if not page.exists():
        raise HTTPException(status_code=404, detail="Gateway model detail page not found")
    return page.read_text(encoding="utf-8")


@app.get("/gateway/history", response_class=HTMLResponse)
def gateway_history_page():
    page = Path("templates/gateway/history.html")
    if not page.exists():
        raise HTTPException(status_code=404, detail="Gateway history page not found")
    return page.read_text(encoding="utf-8")


@app.get("/gateway/finance", response_class=HTMLResponse)
def gateway_finance_page():
    page = Path("templates/gateway/finance.html")
    if not page.exists():
        raise HTTPException(status_code=404, detail="Gateway finance page not found")
    return page.read_text(encoding="utf-8")


@app.get("/gateway/admin", response_class=HTMLResponse)
def gateway_admin_page():
    page = Path("templates/gateway/admin.html")
    if not page.exists():
        raise HTTPException(status_code=404, detail="Gateway admin page not found")
    return page.read_text(encoding="utf-8")


@app.get("/gateway/admin/users/ui", response_class=HTMLResponse)
def gateway_admin_users_page():
    page = Path("templates/gateway/admin-users.html")
    if not page.exists():
        raise HTTPException(status_code=404, detail="Gateway admin users page not found")
    return page.read_text(encoding="utf-8")


@app.get("/gateway/admin/models/ui", response_class=HTMLResponse)
def gateway_admin_models_page():
    page = Path("templates/gateway/admin-models.html")
    if not page.exists():
        raise HTTPException(status_code=404, detail="Gateway admin models page not found")
    return page.read_text(encoding="utf-8")


@app.get("/gateway/admin/finance/ui", response_class=HTMLResponse)
def gateway_admin_finance_page():
    page = Path("templates/gateway/admin-finance.html")
    if not page.exists():
        raise HTTPException(status_code=404, detail="Gateway admin finance page not found")
    return page.read_text(encoding="utf-8")


@app.post("/gateway/register", response_model=GatewayUserResponse)
def gateway_register(payload: GatewayUserRegisterRequest):
    email = normalize_email(payload.email)

    password_salt, password_digest = hash_password(payload.password)
    password_hash = f"{password_salt}${password_digest}"
    api_key, _, _, _ = generate_api_key()
    with SessionLocal() as db:
        _ensure_catalog_seeded(db)
        exists = db.query(GatewayUser).filter(GatewayUser.email == email).first()
        if exists:
            raise HTTPException(status_code=409, detail="Email already registered")
        role = "admin" if _is_admin_email(email) else "user"
        user = GatewayUser(
            email=email,
            password_hash=password_hash,
            api_key=api_key,
            role=role,
            tokens_balance=0,
            plan="default",
            is_active=True,
        )
        db.add(user)
        db.commit()
        db.refresh(user)
        return GatewayUserResponse(
            user_id=user.id,
            email=user.email,
            api_key=user.api_key,
            role=user.role,
            token_balance=user.tokens_balance,
            tariff_code=user.plan,
            is_active=user.is_active,
        )


@app.post("/gateway/login", response_model=GatewayUserResponse)
def gateway_login(payload: GatewayLoginRequest):
    email = normalize_email(payload.email)
    with SessionLocal() as db:
        _ensure_catalog_seeded(db)
        user = db.query(GatewayUser).filter(GatewayUser.email == email).first()
        if not user or not _verify_gateway_user_password(user, payload.password):
            raise HTTPException(status_code=401, detail="Invalid email or password")
        if not user.is_active:
            raise HTTPException(status_code=403, detail="Gateway user is inactive")
        if _is_admin_email(user.email) and user.role != "admin":
            user.role = "admin"
            db.commit()
            db.refresh(user)
        return GatewayUserResponse(
            user_id=user.id,
            email=user.email,
            api_key=user.api_key,
            role=user.role,
            token_balance=user.tokens_balance,
            tariff_code=user.plan,
            is_active=user.is_active,
        )


@app.get("/gateway/me", response_model=GatewayMeResponse)
def gateway_me(user: GatewayUser = Depends(_get_gateway_user)):
    return GatewayMeResponse(
        user_id=user.id,
        email=user.email,
        role=user.role,
        tariff_code=user.plan,
        token_balance=user.tokens_balance,
        is_active=user.is_active,
        created_at=user.created_at,
    )


@app.get("/gateway/usage", response_model=GatewayUsageLogsResponse)
def gateway_usage(limit: int = Query(20, ge=1, le=200), user: GatewayUser = Depends(_get_gateway_user)):
    with SessionLocal() as db:
        rows = (
            db.query(GatewayUsageLog)
            .filter(GatewayUsageLog.user_id == user.id)
            .order_by(GatewayUsageLog.id.desc())
            .limit(limit)
            .all()
        )
    return GatewayUsageLogsResponse(
        items=[
            GatewayUsageLogItem(
                id=row.id,
                model_id=row.model_key,
                provider=row.provider,
                prompt_tokens=row.prompt_tokens,
                completion_tokens=row.completion_tokens,
                total_tokens=row.total_tokens,
                tokens_spent=row.cost_tokens,
                success=row.success,
                error_message=row.error_message,
                created_at=row.created_at,
            )
            for row in rows
        ]
    )


@app.get("/gateway/audit/balance", response_model=GatewayBalanceAuditResponse)
def gateway_balance_audit(limit: int = Query(20, ge=1, le=200), user: GatewayUser = Depends(_get_gateway_user)):
    with SessionLocal() as db:
        rows = (
            db.query(GatewayBalanceAuditLog)
            .filter(GatewayBalanceAuditLog.user_id == user.id)
            .order_by(GatewayBalanceAuditLog.id.desc())
            .limit(limit)
            .all()
        )
    return GatewayBalanceAuditResponse(
        items=[_to_balance_audit_item(row) for row in rows]
    )


@app.get("/gateway/admin/users", response_model=GatewayAdminUsersResponse)
def gateway_admin_users(
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    search: str | None = Query(default=None, min_length=1, max_length=255),
    include_inactive: bool = Query(default=False),
    _: None = Depends(_verify_gateway_admin_key),
):
    with SessionLocal() as db:
        base_query = db.query(GatewayUser)
        if not include_inactive:
            base_query = base_query.filter(GatewayUser.is_active.is_(True))
        if search:
            email_like = f"%{search.strip().lower()}%"
            base_query = base_query.filter(func.lower(GatewayUser.email).like(email_like))

        total_count = base_query.count()
        users = (
            base_query.order_by(GatewayUser.id.asc())
            .offset(offset)
            .limit(limit)
            .all()
        )

        usage_map: dict[int, tuple[int, int, datetime | None]] = {}
        user_ids = [row.id for row in users]
        if user_ids:
            usage_rows = (
                db.query(
                    GatewayUsageLog.user_id,
                    func.count(GatewayUsageLog.id),
                    func.coalesce(func.sum(GatewayUsageLog.cost_tokens), 0),
                    func.max(GatewayUsageLog.created_at),
                )
                .filter(GatewayUsageLog.user_id.in_(user_ids))
                .group_by(GatewayUsageLog.user_id)
                .all()
            )
            usage_map = {
                int(row[0]): (int(row[1] or 0), int(row[2] or 0), row[3])
                for row in usage_rows
            }

    return GatewayAdminUsersResponse(
        total_count=total_count,
        users=[
            GatewayAdminUserItem(
                user_id=row.id,
                email=row.email,
                role=row.role,
                tariff_code=row.plan,
                token_balance=row.tokens_balance,
                is_active=row.is_active,
                created_at=row.created_at,
                total_requests=usage_map.get(row.id, (0, 0, None))[0],
                total_tokens_spent=usage_map.get(row.id, (0, 0, None))[1],
                last_usage_at=usage_map.get(row.id, (0, 0, None))[2],
            )
            for row in users
        ],
    )


@app.patch("/gateway/admin/users/{user_id}", response_model=GatewayUserResponse)
def gateway_admin_update_user(
    user_id: int,
    payload: GatewayAdminUserUpdateRequest,
    _: None = Depends(_verify_gateway_admin_key),
):
    valid_roles = {"user", "admin"}
    with SessionLocal() as db:
        _ensure_catalog_seeded(db)
        user_row = db.query(GatewayUser).filter(GatewayUser.id == user_id).first()
        if not user_row:
            raise HTTPException(status_code=404, detail="Gateway user not found")
        original_balance = int(user_row.tokens_balance)

        if payload.email is not None:
            normalized_email = normalize_email(payload.email)
            exists = (
                db.query(GatewayUser)
                .filter(GatewayUser.email == normalized_email, GatewayUser.id != user_row.id)
                .first()
            )
            if exists:
                raise HTTPException(status_code=409, detail="Email already registered by another user")
            user_row.email = normalized_email
            if _is_admin_email(normalized_email):
                user_row.role = "admin"

        if payload.tariff_code is not None:
            user_row.plan = payload.tariff_code

        if payload.role is not None:
            normalized_role = payload.role.strip().lower()
            if normalized_role not in valid_roles:
                raise HTTPException(status_code=400, detail=f"Unsupported role: {payload.role}")
            user_row.role = normalized_role

        if payload.set_balance_tokens is not None:
            user_row.tokens_balance = payload.set_balance_tokens

        if payload.add_tokens is not None:
            updated_balance = user_row.tokens_balance + payload.add_tokens
            if updated_balance < 0:
                raise HTTPException(status_code=400, detail="Resulting token balance cannot be negative")
            user_row.tokens_balance = updated_balance

        if int(user_row.tokens_balance) != original_balance:
            _log_balance_audit(
                db=db,
                user_id=user_row.id,
                action="admin_adjustment",
                delta_tokens=int(user_row.tokens_balance) - original_balance,
                balance_before=original_balance,
                balance_after=int(user_row.tokens_balance),
                actor="admin",
                actor_reference="gateway-admin",
                reason=payload.balance_reason or "Admin balance update",
            )

        if payload.is_active is not None:
            user_row.is_active = payload.is_active

        if payload.regenerate_api_key:
            new_key, _, _, _ = generate_api_key()
            user_row.api_key = new_key

        db.commit()
        db.refresh(user_row)
        return GatewayUserResponse(
            user_id=user_row.id,
            email=user_row.email,
            api_key=user_row.api_key,
            role=user_row.role,
            token_balance=user_row.tokens_balance,
            tariff_code=user_row.plan,
            is_active=user_row.is_active,
        )


@app.get("/gateway/admin/users/{user_id}/usage", response_model=GatewayUsageLogsResponse)
def gateway_admin_user_usage(
    user_id: int,
    limit: int = Query(100, ge=1, le=500),
    _: None = Depends(_verify_gateway_admin_key),
):
    with SessionLocal() as db:
        exists = db.query(GatewayUser.id).filter(GatewayUser.id == user_id).first()
        if not exists:
            raise HTTPException(status_code=404, detail="Gateway user not found")
        rows = (
            db.query(GatewayUsageLog)
            .filter(GatewayUsageLog.user_id == user_id)
            .order_by(GatewayUsageLog.id.desc())
            .limit(limit)
            .all()
        )
    return GatewayUsageLogsResponse(
        items=[
            GatewayUsageLogItem(
                id=row.id,
                model_id=row.model_key,
                provider=row.provider,
                prompt_tokens=row.prompt_tokens,
                completion_tokens=row.completion_tokens,
                total_tokens=row.total_tokens,
                tokens_spent=row.cost_tokens,
                success=row.success,
                error_message=row.error_message,
                created_at=row.created_at,
            )
            for row in rows
        ]
    )


@app.get("/gateway/admin/audit/balance", response_model=GatewayBalanceAuditResponse)
def gateway_admin_balance_audit(
    limit: int = Query(100, ge=1, le=500),
    user_id: int | None = Query(default=None, ge=1),
    _: None = Depends(_verify_gateway_admin_key),
):
    with SessionLocal() as db:
        query = db.query(GatewayBalanceAuditLog)
        if user_id is not None:
            exists = db.query(GatewayUser.id).filter(GatewayUser.id == user_id).first()
            if not exists:
                raise HTTPException(status_code=404, detail="Gateway user not found")
            query = query.filter(GatewayBalanceAuditLog.user_id == user_id)
        rows = query.order_by(GatewayBalanceAuditLog.id.desc()).limit(limit).all()
    return GatewayBalanceAuditResponse(items=[_to_balance_audit_item(row) for row in rows])


@app.delete("/gateway/admin/users/{user_id}")
def gateway_admin_delete_user(
    user_id: int,
    _: None = Depends(_verify_gateway_admin_key),
):
    with SessionLocal() as db:
        user_row = db.query(GatewayUser).filter(GatewayUser.id == user_id).first()
        if not user_row:
            raise HTTPException(status_code=404, detail="Gateway user not found")
        db.query(GatewayBalanceAuditLog).filter(GatewayBalanceAuditLog.user_id == user_id).delete()
        db.query(GatewayUsageLog).filter(GatewayUsageLog.user_id == user_id).delete()
        db.delete(user_row)
        db.commit()
    return {"deleted": True, "user_id": user_id}


@app.get("/gateway/models", response_model=GatewayCatalogResponse)
def gateway_models(_: GatewayUser = Depends(_get_gateway_user)):
    with SessionLocal() as db:
        _ensure_catalog_seeded(db)
        rows = db.query(GatewayModel).filter(GatewayModel.is_active.is_(True)).order_by(GatewayModel.id.asc()).all()
    return GatewayCatalogResponse(
        models=[_model_item_from_row(row) for row in rows]
    )


@app.post("/gateway/estimate-cost", response_model=GatewayEstimateCostResponse)
def gateway_estimate_cost(payload: GatewayEstimateCostRequest, user: GatewayUser = Depends(_get_gateway_user)):
    prompt = payload.prompt.strip()
    if not prompt:
        raise HTTPException(status_code=400, detail="prompt is required")
    with SessionLocal() as db:
        _ensure_catalog_seeded(db)
        model = _resolve_model_for_request(db, payload.model_id)
        price_per_1k = _effective_model_price_per_1k(model)
        prompt_tokens, completion_tokens, estimated_charge = _estimate_charge_for_prompt(prompt, price_per_1k)
        total_tokens = prompt_tokens + completion_tokens
        user_row = db.query(GatewayUser).filter(GatewayUser.id == user.id).first()
        if not user_row:
            raise HTTPException(status_code=404, detail="Gateway user not found")
        balance_after = int(user_row.tokens_balance) - int(estimated_charge)
    return GatewayEstimateCostResponse(
        model_id=model.model_key,
        provider=model.provider,
        estimated_prompt_tokens=prompt_tokens,
        estimated_response_tokens=completion_tokens,
        estimated_total_tokens=total_tokens,
        estimated_tokens_to_charge=int(estimated_charge),
        price_per_1k_tokens=float(price_per_1k),
        balance_after_estimate=balance_after,
    )


@app.get("/gateway/admin/models", response_model=GatewayCatalogResponse)
def gateway_admin_models(_: GatewayUser = Depends(_verify_gateway_admin_key)):
    with SessionLocal() as db:
        _ensure_catalog_seeded(db)
        rows = db.query(GatewayModel).order_by(GatewayModel.id.asc()).all()
    return GatewayCatalogResponse(models=[_model_item_from_row(row) for row in rows])


@app.get("/gateway/models/{model_id:path}", response_model=GatewayModelItem)
def gateway_model_detail(model_id: str, _: GatewayUser = Depends(_get_gateway_user)):
    with SessionLocal() as db:
        _ensure_catalog_seeded(db)
        row = _resolve_model_for_request(db, model_id)
        return _model_item_from_row(row)


@app.post("/gateway/admin/models", response_model=GatewayModelItem)
def gateway_admin_create_model(
    payload: GatewayAdminModelCreateRequest,
    _: GatewayUser = Depends(_verify_gateway_admin_key),
):
    model_id = payload.model_id.strip().lower()
    with SessionLocal() as db:
        exists = (
            db.query(GatewayModel.id)
            .filter(func.lower(GatewayModel.model_key) == model_id)
            .first()
        )
        if exists:
            raise HTTPException(status_code=409, detail=f"Model already exists: {model_id}")
        row = GatewayModel(
            model_key=model_id,
            display_name=payload.display_name.strip(),
            provider=payload.provider.strip().lower(),
            target_model=payload.target_model.strip(),
            price_per_1k_tokens=float(payload.price_per_1k_tokens),
            external_price_per_1k_tokens=(
                None
                if payload.external_price_per_1k_tokens is None
                else float(payload.external_price_per_1k_tokens)
            ),
            markup_percent=float(payload.markup_percent),
            is_active=payload.is_active,
        )
        db.add(row)
        db.commit()
        db.refresh(row)
        return _model_item_from_row(row)


@app.patch("/gateway/admin/models/{model_id:path}", response_model=GatewayModelItem)
def gateway_admin_update_model(
    model_id: str,
    payload: GatewayAdminModelUpdateRequest,
    _: GatewayUser = Depends(_verify_gateway_admin_key),
):
    with SessionLocal() as db:
        _ensure_catalog_seeded(db)
        row = db.query(GatewayModel).filter(func.lower(GatewayModel.model_key) == model_id.strip().lower()).first()
        if not row:
            row = db.query(GatewayModel).filter(func.lower(GatewayModel.target_model) == model_id.strip().lower()).first()
        if not row:
            raise HTTPException(status_code=404, detail=f"Unknown model_id: {model_id}")
        if payload.display_name is not None:
            row.display_name = payload.display_name.strip()
        if payload.target_model is not None:
            row.target_model = payload.target_model.strip()
        if payload.provider is not None:
            row.provider = payload.provider.strip().lower()
        if payload.price_per_1k_tokens is not None:
            row.price_per_1k_tokens = float(payload.price_per_1k_tokens)
        if payload.external_price_per_1k_tokens is not None:
            row.external_price_per_1k_tokens = float(payload.external_price_per_1k_tokens)
        if payload.markup_percent is not None:
            row.markup_percent = float(payload.markup_percent)
        if payload.is_active is not None:
            row.is_active = payload.is_active
        db.commit()
        db.refresh(row)
        return _model_item_from_row(row)


@app.delete("/gateway/admin/models/{model_id:path}")
def gateway_admin_delete_model(
    model_id: str,
    _: GatewayUser = Depends(_verify_gateway_admin_key),
):
    normalized = model_id.strip().lower()
    with SessionLocal() as db:
        row = (
            db.query(GatewayModel)
            .filter(func.lower(GatewayModel.model_key) == normalized)
            .first()
        )
        if not row:
            row = (
                db.query(GatewayModel)
                .filter(func.lower(GatewayModel.target_model) == normalized)
                .first()
            )
        if not row:
            raise HTTPException(status_code=404, detail=f"Unknown model_id: {model_id}")
        if db.query(func.count(GatewayModel.id)).scalar() == 1:
            raise HTTPException(status_code=400, detail="At least one model must remain in catalog")
        db.delete(row)
        db.commit()
    return {"deleted": True, "model_id": model_id}


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
        balance_before = int(row.tokens_balance)
        row.tokens_balance += payload.tokens
        _log_balance_audit(
            db=db,
            user_id=row.id,
            action="self_topup",
            delta_tokens=int(payload.tokens),
            balance_before=balance_before,
            balance_after=int(row.tokens_balance),
            actor="user",
            actor_reference=row.email,
            reason="Manual top-up from gateway cabinet/API",
        )
        db.commit()
        db.refresh(row)
        return GatewayTopUpResponse(user_id=row.id, token_balance=row.tokens_balance)


@app.post("/gateway/generate", response_model=GatewayGenerateResponse)
def gateway_generate(payload: GatewayGenerateRequest, user: GatewayUser = Depends(_get_gateway_user)):
    prompt = payload.prompt.strip()
    if not prompt:
        raise HTTPException(status_code=400, detail="prompt is required")
    messages = [{"role": "user", "content": prompt}]

    with SessionLocal() as db:
        _ensure_catalog_seeded(db)
        model_row = _resolve_model_for_request(db, payload.model_id)
        provider = model_row.provider
        upstream_model = model_row.target_model
        model_key = model_row.model_key
        user_row = db.query(GatewayUser).filter(GatewayUser.id == user.id, GatewayUser.is_active.is_(True)).first()
        if not user_row:
            raise HTTPException(status_code=401, detail="Gateway user inactive")

        try:
            if provider == "ollama":
                content = run_chat_mode(client=client, model=upstream_model, prompt=prompt)
                prompt_tokens = estimate_messages_tokens(messages)
                completion_tokens = estimate_text_tokens(content)
                total_tokens = prompt_tokens + completion_tokens
            elif provider == "openai":
                content, prompt_tokens, completion_tokens, total_tokens = call_openai_proxy(
                    model=upstream_model,
                    messages=messages,
                    temperature=payload.temperature,
                    max_tokens=payload.max_tokens,
                )
            else:
                raise RuntimeError(f"Unsupported provider: {provider}")

            cost_tokens = _charge_for_model(total_tokens, model_row)
            if user_row.tokens_balance < cost_tokens:
                raise HTTPException(
                    status_code=402,
                    detail=(
                        f"Insufficient token balance. Need {cost_tokens}, "
                        f"available {user_row.tokens_balance}"
                    ),
                )

            user_row.tokens_balance -= cost_tokens
            _log_balance_audit(
                db=db,
                user_id=user_row.id,
                action="model_request_charge",
                delta_tokens=-int(cost_tokens),
                balance_before=int(user_row.tokens_balance) + int(cost_tokens),
                balance_after=int(user_row.tokens_balance),
                actor="system",
                actor_reference=provider,
                reason=f"Charge for {model_key}",
            )
            db.add(
                GatewayUsageLog(
                    user_id=user_row.id,
                    model_key=model_key,
                    provider=provider,
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
                provider=provider,
                model_id=model_key,
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
                    model_key=model_key,
                    provider=provider,
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


@app.get("/v1/models")
def openai_compatible_models(user: GatewayUser = Depends(_get_gateway_user_from_bearer)):
    _ = user
    with SessionLocal() as db:
        _ensure_catalog_seeded(db)
        rows = db.query(GatewayModel).filter(GatewayModel.is_active.is_(True)).order_by(GatewayModel.id.asc()).all()
    model_ids = [row.model_key for row in rows]
    return {
        "object": "list",
        "data": [
            {
                "id": model_id,
                "object": "model",
                "owned_by": "ai-servise-gateway",
            }
            for model_id in model_ids
        ],
    }


@app.post("/v1/chat/completions")
def openai_compatible_chat_completions(
    payload: GatewayChatRequest,
    user: GatewayUser = Depends(_get_gateway_user_from_bearer),
):
    prompt = "\n".join(message.content for message in payload.messages if message.role == "user").strip()
    if not prompt:
        prompt = payload.messages[-1].content.strip()
    generate_payload = GatewayGenerateRequest(
        model_id=payload.model,
        prompt=prompt,
        max_tokens=payload.max_tokens,
        temperature=payload.temperature,
    )
    generated = gateway_generate(generate_payload, user)
    return {
        "id": f"chatcmpl-{uuid.uuid4().hex[:24]}",
        "object": "chat.completion",
        "created": int(datetime.now(timezone.utc).timestamp()),
        "model": generated.model_id,
        "choices": [
            {
                "index": 0,
                "finish_reason": "stop",
                "message": {
                    "role": "assistant",
                    "content": generated.answer,
                },
            }
        ],
        "usage": {
            "prompt_tokens": generated.prompt_tokens,
            "completion_tokens": generated.completion_tokens,
            "total_tokens": generated.total_tokens,
        },
    }


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
