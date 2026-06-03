"""Воркер доставки лидов в CRM: очередь + ретраи с бэкоффом + защита от двойной отправки.

Один прогон:
  1) возвращает зависшие в sending (упавший воркер) обратно в retry;
  2) атомарно забирает пачку готовых лидов (new/retry, у кого подошёл срок) и
     помечает sending — FOR UPDATE SKIP LOCKED, поэтому два воркера не возьмут один лид;
  3) шлёт каждый лид в CRM и проставляет done | retry(+next_attempt_at) | error.

Бэкофф: после 1-й ошибки +15 мин, после 2-й +1 ч, после 3-й +6 ч; дальше — error.

Запуск разово:  docker compose exec api python -m app.crm_dispatch
Запуск циклом:  python -m app.crm_dispatch --loop   (сервис crm-worker в compose)
"""
import asyncio
import sys
from datetime import datetime, timedelta, timezone

from sqlalchemy import or_, select, update

from .config import settings
from .crm_client import CRMError, CRMNotConfigured, send_lead
from .db import async_session_maker, engine
from .models import Base, Lead
from .quiz_catalog import resolve
from .quiz_seed import load_maps, seed_if_empty

# Бэкофф между попытками. Длина списка = число ретраев; затем лид уходит в error.
BACKOFF = [timedelta(minutes=15), timedelta(hours=1), timedelta(hours=6)]
# «Зависший» sending вернуть в retry. ИНВАРИАНТ: STALE_SENDING должен быть заведомо
# больше, чем один прогон может слать пачку (crm_batch_size × таймаут отправки),
# иначе реапер «воскресит» лид, который этот же воркер ещё досылает → дубль.
# Сейчас: 50 × 20с ≈ 17 мин < 30 мин — с запасом. Воркер ДОЛЖЕН быть в одном экземпляре
# (compose: один crm-worker; ручной прогон не запускать параллельно с --loop).
STALE_SENDING = timedelta(minutes=30)
POLL_INTERVAL = 900  # секунд между прогонами в режиме --loop (15 мин)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _configured() -> str | None:
    """Причина, по которой отправлять нельзя (или None если можно)."""
    if settings.crm_mode == "off":
        return "crm_mode=off"
    if settings.crm_mode == "bitrix" and not settings.crm_webhook_url:
        return "crm_mode=bitrix, но CRM_WEBHOOK_URL пуст"
    return None


async def _reset_stale_sending(session) -> int:
    """Лиды, застрявшие в sending (воркер упал между claim и финишем), вернуть в retry."""
    cutoff = _now() - STALE_SENDING
    res = await session.execute(
        update(Lead)
        .where(Lead.crm_status == "sending", Lead.crm_last_attempt_at < cutoff)
        .values(crm_status="retry", crm_next_attempt_at=_now())
    )
    await session.commit()
    return res.rowcount or 0


async def _claim_batch(session, limit: int) -> list[Lead]:
    """Атомарно забрать пачку готовых к отправке лидов и пометить sending.

    FOR UPDATE SKIP LOCKED: блокировка держится до commit() ниже; параллельный воркер
    эти строки пропустит. После commit они уже в статусе sending — повторно не заберутся.
    """
    now = _now()
    leads = (await session.execute(
        select(Lead)
        .where(
            Lead.crm_status.in_(("new", "retry")),
            or_(Lead.crm_next_attempt_at.is_(None), Lead.crm_next_attempt_at <= now),
        )
        .order_by(Lead.id)
        .limit(limit)
        .with_for_update(skip_locked=True)
    )).scalars().all()
    for lead in leads:
        lead.crm_status = "sending"
        lead.crm_attempts += 1
        lead.crm_last_attempt_at = now
    await session.commit()
    return leads


async def _mark_done(session, lead, ref: str) -> None:
    lead.crm_status = "done"
    lead.crm_sent_at = _now()
    lead.crm_ref = ref
    lead.crm_last_error = None
    await session.commit()


async def _mark_failed(session, lead, error: str) -> str:
    """retry (с бэкоффом) или error, если ретраи исчерпаны. Возвращает итоговый статус."""
    lead.crm_last_error = (error or "")[:500]
    idx = lead.crm_attempts - 1  # 0-based номер уже сделанной попытки
    if idx < len(BACKOFF):
        lead.crm_status = "retry"
        lead.crm_next_attempt_at = _now() + BACKOFF[idx]
    else:
        lead.crm_status = "error"
        lead.crm_next_attempt_at = None
    await session.commit()
    return lead.crm_status


async def _unclaim(session, lead) -> None:
    """Откатить claim (CRM не настроена) — не жжём попытку."""
    lead.crm_attempts -= 1
    lead.crm_status = "new" if lead.crm_attempts <= 0 else "retry"
    lead.crm_last_attempt_at = None
    await session.commit()


async def process_batch(session) -> dict:
    """Один прогон очереди. Возвращает статистику."""
    reason = _configured()
    if reason:
        return {"skipped": reason}

    reset = await _reset_stale_sending(session)
    questions, answers = await load_maps(session)
    leads = await _claim_batch(session, settings.crm_batch_size)

    done = retried = errored = 0
    for i, lead in enumerate(leads):
        quiz = resolve(lead.quiz_data, questions, answers)
        try:
            ref = await send_lead(lead, quiz)
        except CRMNotConfigured as exc:
            # отправлять нечем — откатываем claim у текущего и всех оставшихся (не жжём попытки)
            for pending in leads[i:]:
                await _unclaim(session, pending)
            print(f"crm_dispatch: CRM не настроена — стоп: {exc}", flush=True)
            break
        except CRMError as exc:
            status = await _mark_failed(session, lead, str(exc))
            errored += status == "error"
            retried += status == "retry"
            continue
        await _mark_done(session, lead, ref)
        done += 1

    return {"reset_stale": reset, "claimed": len(leads), "done": done,
            "retry": retried, "error": errored}


async def _cycle() -> None:
    try:
        async with async_session_maker() as session:
            result = await process_batch(session)
        print(f"crm_dispatch: {result}", flush=True)
    except Exception as exc:  # noqa: BLE001 — воркер не должен падать на одной ошибке
        print(f"crm_dispatch: ошибка прогона: {exc}", flush=True)


async def _amain() -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    # Сид справочника — один раз при старте (а не каждый цикл).
    async with async_session_maker() as session:
        await seed_if_empty(session)
    if "--loop" in sys.argv:
        print(f"crm_dispatch: запущен цикл (каждые {POLL_INTERVAL}s), режим={settings.crm_mode}", flush=True)
        while True:
            await _cycle()
            await asyncio.sleep(POLL_INTERVAL)
    else:
        await _cycle()


if __name__ == "__main__":
    asyncio.run(_amain())
