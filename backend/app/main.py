"""IPRAhelp API — приём заявок с лендинга и выгрузка лидов."""
import csv
import io
import json
import re
from contextlib import asynccontextmanager
from datetime import datetime, timedelta

from fastapi import Depends, FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from slowapi import Limiter
from slowapi.errors import RateLimitExceeded
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from .config import settings
from .db import async_session_maker, get_session, init_db
from .models import CertPrice, Lead, QuizDictionary, User
from .quiz_catalog import resolve
from .quiz_seed import load_maps, seed_if_empty
from .schemas import LeadIn, LeadOut
from .security import client_ip, rate_limit_key, require_admin
from .stats import MSK, real_helped_today, simulated_helped_today

limiter = Limiter(key_func=rate_limit_key)

# Кеш для /api/stats — значение меняется медленно, БД дёргать на каждый заход не нужно.
_stats_cache: dict = {"value": None, "expires": None}

# Кеш для /api/cert-amounts — справочник меняется ежеквартально.
_certs_cache: dict = {"value": None, "expires": None}

# Кеш справочника квиза (quiz_dictionary): меняется редко.
_quizdict_cache: dict = {"value": None, "expires": None}

CSV_COLUMNS = [
    "id", "user_id", "created_at", "form_type", "name", "contact", "phone", "consent",
    "quiz_data", "quiz_answers",
    "utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content",
    "referrer", "page_url", "ip", "user_agent",
]


async def load_quiz_dict(session: AsyncSession):
    """Справочник квиза из БД (с кешем 10 мин). См. quiz_seed.load_maps."""
    now = datetime.now(MSK)
    if _quizdict_cache["expires"] and now < _quizdict_cache["expires"]:
        return _quizdict_cache["value"]
    value = await load_maps(session)
    _quizdict_cache["value"] = value
    _quizdict_cache["expires"] = now + timedelta(minutes=10)
    return value


def normalize_phone(value: str) -> str:
    """Только цифры; ведущая 8 → 7 (российский формат). Напр. 79991234567."""
    digits = re.sub(r"\D", "", value or "")
    if digits.startswith("8"):
        digits = "7" + digits[1:]
    return digits


def csv_safe(value) -> str:
    """Анти-CSV-инъекция: экранируем ячейки, начинающиеся с = + - @ \\t \\r."""
    s = "" if value is None else str(value)
    if s[:1] in ("=", "+", "-", "@", "\t", "\r"):
        s = "'" + s
    return s


WEAK_TOKENS = {"", "change-me"}


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Не даём подняться со слабым/дефолтным админ-токеном — иначе вся база заявок открыта.
    if settings.admin_token in WEAK_TOKENS or len(settings.admin_token) < 16:
        raise RuntimeError(
            "ADMIN_TOKEN не задан или слишком слабый (нужно >=16 символов). "
            "Сгенерируйте: openssl rand -hex 32"
        )
    await init_db()
    # Наполняем справочник квиза при первом запуске (правки в БД не затираются).
    async with async_session_maker() as session:
        await seed_if_empty(session)
    yield


app = FastAPI(
    title="IPRAhelp API",
    version="1.0.0",
    lifespan=lifespan,
    docs_url="/docs" if settings.docs_enabled else None,
    redoc_url="/redoc" if settings.docs_enabled else None,
    openapi_url="/openapi.json" if settings.docs_enabled else None,
)
app.state.limiter = limiter


@app.exception_handler(RateLimitExceeded)
async def _rate_limit_handler(request: Request, exc: RateLimitExceeded):
    return JSONResponse(status_code=429, content={"ok": False, "error": "too_many_requests"})


app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.origins_list,
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type", "X-Admin-Token"],
)


@app.get("/api/health")
async def health():
    return {"status": "ok"}


@app.get("/api/quiz-catalog")
async def quiz_catalog_endpoint(session: AsyncSession = Depends(get_session)):
    """Справочник квиза из БД: вопросы и все варианты ответов (коды → подписи как на сайте)."""
    rows = (await session.execute(
        select(QuizDictionary).order_by(
            QuizDictionary.field, QuizDictionary.type, QuizDictionary.context, QuizDictionary.code
        )
    )).scalars().all()
    questions: dict = {}
    answers: dict = {}
    for r in rows:
        if r.type == "question":
            questions[r.field] = r.label
        else:
            answers.setdefault(r.field, {}).setdefault(r.context or "", {})[r.code] = r.label
    return {"questions": questions, "answers": answers}


@app.get("/api/stats")
async def stats(session: AsyncSession = Depends(get_session)):
    """Публичный счётчик «обратились сегодня». Кешируется на 30 секунд."""
    now = datetime.now(MSK)
    if _stats_cache["expires"] and now < _stats_cache["expires"]:
        return _stats_cache["value"]

    if settings.stats_mode == "real":
        helped = await real_helped_today(session, now)
    else:
        helped = simulated_helped_today(now)

    total_leads = (await session.execute(select(func.count()).select_from(Lead))).scalar_one()
    payload = {
        "helped_today": helped,
        "helped_total": settings.stats_baseline + int(total_leads),
    }
    _stats_cache["value"] = payload
    _stats_cache["expires"] = now + timedelta(seconds=30)
    return payload


@app.get("/api/cert-amounts")
async def cert_amounts(session: AsyncSession = Depends(get_session)):
    """Справочник сумм сертификата СФР (регион × ТСР) для калькулятора. Кеш 10 минут."""
    now = datetime.now(MSK)
    if _certs_cache["expires"] and now < _certs_cache["expires"]:
        return _certs_cache["value"]

    rows = (await session.execute(select(CertPrice))).scalars().all()
    regions: dict = {}
    tsr: dict = {}
    data: dict = {}
    latest = None
    for r in rows:
        regions[r.region_code] = r.region_name
        tsr[r.tsr_code] = r.tsr_name
        data.setdefault(r.region_code, {})[r.tsr_code] = r.amount
        if r.updated_at and (latest is None or r.updated_at > latest):
            latest = r.updated_at

    payload = {
        "regions": regions,
        "tsr": tsr,
        "data": data,
        "meta": {
            "source": "ktsr.sfr.gov.ru",
            "parsed": latest.date().isoformat() if latest else None,
        },
    }
    _certs_cache["value"] = payload
    _certs_cache["expires"] = now + timedelta(minutes=10)
    return payload


@app.post("/api/leads")
@limiter.limit(settings.rate_limit)
@limiter.limit("120/minute", key_func=lambda request: "global")
async def create_lead(
    request: Request,
    lead: LeadIn,
    session: AsyncSession = Depends(get_session),
):
    # honeypot заполнен => это бот. Отвечаем «успехом», но ничего не сохраняем.
    if lead.company:
        return {"ok": True}

    phone = normalize_phone(lead.contact)

    # Клиент уникален по номеру телефона: находим существующего или создаём нового.
    user = (await session.execute(select(User).where(User.phone == phone))).scalar_one_or_none()
    if user is None:
        user = User(phone=phone, name=lead.name or None, consent=lead.consent)
        session.add(user)
        try:
            await session.flush()  # получаем user.id
        except IntegrityError:
            # параллельно создали такого же клиента — берём существующего
            await session.rollback()
            user = (await session.execute(select(User).where(User.phone == phone))).scalar_one()
    else:
        if lead.name:
            user.name = lead.name
        if lead.consent:
            user.consent = True

    # Заявок у клиента может быть сколько угодно — каждая ссылается на его id.
    row = Lead(
        user_id=user.id,
        form_type=lead.form_type,
        name=lead.name or None,
        contact=lead.contact,
        phone=phone or None,
        consent=lead.consent,
        quiz_data=lead.quiz_data,
        utm_source=lead.utm_source,
        utm_medium=lead.utm_medium,
        utm_campaign=lead.utm_campaign,
        utm_term=lead.utm_term,
        utm_content=lead.utm_content,
        referrer=lead.referrer,
        page_url=lead.page_url,
        ip=client_ip(request),
        user_agent=request.headers.get("user-agent", "")[:400],
    )
    session.add(row)
    await session.commit()
    # id и нормализованный phone присваиваются в БД; наружу их не возвращаем (минимизация)
    return {"ok": True}


@app.get(
    "/api/leads",
    response_model=list[LeadOut],
    dependencies=[Depends(require_admin)],
)
async def list_leads(
    limit: int = 100,
    offset: int = 0,
    session: AsyncSession = Depends(get_session),
):
    limit = max(1, min(limit, 1000))
    offset = max(0, offset)
    questions, answers = await load_quiz_dict(session)
    result = await session.execute(
        select(Lead).order_by(Lead.id.desc()).limit(limit).offset(offset)
    )
    leads = list(result.scalars().all())
    # Сопоставляем коды ответов со справочником → человеческие вопрос+ответ (для CRM)
    for ld in leads:
        ld.quiz = resolve(ld.quiz_data, questions, answers)
    return leads


@app.get("/api/users", dependencies=[Depends(require_admin)])
async def list_users(
    limit: int = 100,
    offset: int = 0,
    session: AsyncSession = Depends(get_session),
):
    """Уникальные клиенты (по телефону) + число их заявок."""
    limit = max(1, min(limit, 1000))
    offset = max(0, offset)
    result = await session.execute(
        select(User, func.count(Lead.id))
        .outerjoin(Lead, Lead.user_id == User.id)
        .group_by(User.id)
        .order_by(User.id.desc())
        .limit(limit)
        .offset(offset)
    )
    return [
        {
            "id": u.id,
            "phone": u.phone,
            "name": u.name,
            "consent": u.consent,
            "created_at": u.created_at.isoformat() if u.created_at else None,
            "leads": cnt,
        }
        for u, cnt in result.all()
    ]


@app.get("/api/crm-status", dependencies=[Depends(require_admin)])
async def crm_status(session: AsyncSession = Depends(get_session)):
    """Сводка очереди доставки лидов в CRM: сколько в каком статусе."""
    rows = (await session.execute(
        select(Lead.crm_status, func.count()).group_by(Lead.crm_status)
    )).all()
    return {"mode": settings.crm_mode, "by_status": {s: c for s, c in rows}}


@app.post("/api/leads/{lead_id}/crm-retry", dependencies=[Depends(require_admin)])
async def crm_retry(lead_id: int, session: AsyncSession = Depends(get_session)):
    """Вернуть лид в очередь на отправку (например, после статуса error)."""
    lead = await session.get(Lead, lead_id)
    if lead is None:
        return JSONResponse(status_code=404, content={"ok": False, "error": "not_found"})
    lead.crm_status = "new"
    lead.crm_attempts = 0
    lead.crm_next_attempt_at = None
    lead.crm_last_error = None
    await session.commit()
    return {"ok": True, "lead_id": lead_id, "crm_status": "new"}


@app.get("/api/leads.csv", dependencies=[Depends(require_admin)])
async def export_csv(session: AsyncSession = Depends(get_session)):
    questions, answers = await load_quiz_dict(session)
    result = await session.execute(select(Lead).order_by(Lead.id.desc()))
    rows = result.scalars().all()

    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(CSV_COLUMNS)
    for r in rows:
        qa = resolve(r.quiz_data, questions, answers)
        writer.writerow([
            r.id,
            r.user_id or "",
            r.created_at.isoformat() if r.created_at else "",
            r.form_type,
            csv_safe(r.name),
            csv_safe(r.contact),
            csv_safe(r.phone),
            r.consent,
            csv_safe(json.dumps(r.quiz_data, ensure_ascii=False) if r.quiz_data else ""),
            csv_safe("; ".join(f"{x['question']}: {x['answer']}" for x in qa)),
            csv_safe(r.utm_source),
            csv_safe(r.utm_medium),
            csv_safe(r.utm_campaign),
            csv_safe(r.utm_term),
            csv_safe(r.utm_content),
            csv_safe(r.referrer),
            csv_safe(r.page_url),
            csv_safe(r.ip),
            csv_safe(r.user_agent),
        ])
    buf.seek(0)
    return StreamingResponse(
        iter([buf.getvalue()]),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": "attachment; filename=leads.csv"},
    )
