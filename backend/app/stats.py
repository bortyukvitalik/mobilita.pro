"""Счётчик «сколько семей обратились сегодня».

Сейчас работает в режиме ИМИТАЦИИ (STATS_MODE=simulated): число — детерминированная
функция даты и времени по Москве. Свойства, которые делают её правдоподобной:

  * одно и то же число у всех посетителей в один момент (нет разнобоя по вкладкам);
  * монотонный рост в течение рабочего дня (не убывает, не прыгает ступеньками);
  * лёгкая вариация день ото дня (seed из даты) — не одинаково каждый день;
  * рабочие часы 9:00–20:00 МСК, как заявлено на сайте.

Когда обращений станет достаточно — переключить STATS_MODE=real: тогда число
считается из таблицы leads за текущие сутки по МСК. Код для этого уже готов
(real_helped_today) — менять фронтенд не нужно.
"""
import hashlib
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from .models import Lead

# Москва — фиксированный UTC+3 (перевода часов в РФ нет с 2014 г.), tzdata не нужен.
MSK = timezone(timedelta(hours=3), name="MSK")

WORK_START_HOUR = 9
WORK_END_HOUR = 20


def _daily_seed(iso_date: str) -> int:
    """Стабильный seed из даты — одинаков для всех в течение суток."""
    return int(hashlib.sha256(iso_date.encode()).hexdigest()[:8], 16)


def simulated_helped_today(now: datetime) -> int:
    """Имитация числа обращений «сегодня» по времени суток (МСК)."""
    seed = _daily_seed(now.date().isoformat())
    daily_target = 11 + seed % 6          # 11..16 — дневная «норма», меняется по дням
    morning_base = 1 + (seed >> 8) % 2    # 1..2  — задел до открытия

    minutes = now.hour * 60 + now.minute
    start_m, end_m = WORK_START_HOUR * 60, WORK_END_HOUR * 60

    if minutes <= start_m:
        return morning_base
    if minutes >= end_m:
        return daily_target

    frac = (minutes - start_m) / (end_m - start_m)
    shaped = frac ** 1.3                   # ease-in: к середине/концу дня активнее
    value = round(morning_base + (daily_target - morning_base) * shaped)
    return max(morning_base, min(daily_target, value))


def msk_day_start(now: datetime) -> datetime:
    return now.replace(hour=0, minute=0, second=0, microsecond=0)


async def real_helped_today(session: AsyncSession, now: datetime) -> int:
    """Реальное число заявок с начала суток по МСК (для STATS_MODE=real)."""
    start = msk_day_start(now)
    result = await session.execute(
        select(func.count()).select_from(Lead).where(Lead.created_at >= start)
    )
    return int(result.scalar_one())
