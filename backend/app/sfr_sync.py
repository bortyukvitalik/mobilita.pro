"""Парсер справочника сертификата СФР (ktsr.sfr.gov.ru) → таблица cert_prices.

Запуск (внутри docker-сети, где доступны и СФР, и БД):
    docker compose exec api python -m app.sfr_sync

Особенности:
  * пишет в БД ПОСЛЕ КАЖДОГО региона — прогресс не теряется при обрыве;
  * резюмирование: регионы, обновлённые за последние 12 часов, пропускаются
    (повторный запуск после обрыва доделывает остаток);
  * SFR_REGIONS=RU-ALT,RU-MOW — ограничить набор регионов;
  * SFR_FORCE=1 — игнорировать резюмирование (перепарсить всё).

Делает до 89 регионов × 10 ТСР запросов к /result. Запускать ежеквартально.
"""
import asyncio
import html
import os
import re
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from .db import async_session_maker, engine
from .models import Base, CertPrice

BASE = "https://ktsr.sfr.gov.ru/ru-RU/service/compensation"

# Отслеживаемые ТСР: код СФР → короткое название (как в калькуляторе). Тип = первые 2 цифры.
TRACKED = {
    "07-01-01": "Коляска комнатная",
    "07-02-01": "Коляска прогулочная",
    "07-03-01": "Коляска активного типа",
    "07-04-01": "Коляска с электроприводом",
    "06-10-01": "Ходунки",
    "06-10-05": "Ходунки-роллаторы",
    "06-09-01": "Вертикализатор (опора стояния)",
    "08-09-43": "Ортез на нижние конечности",
    "09-01-01": "Обувь ортопедическая",
    "10-01-01": "Матрас противопролежневый",
}


def _fetch(url: str) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (compatible; iprahelp-sync)"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return resp.read().decode("utf-8", "replace")


def _parse_regions(page: str) -> dict[str, str]:
    block = re.search(r'<select[^>]*name="pcc-region"[^>]*>(.*?)</select>', page, re.S | re.I)
    out: dict[str, str] = {}
    if not block:
        return out
    for value, text in re.findall(r'<option[^>]*value="([^"]*)"[^>]*>(.*?)</option>', block.group(1), re.S):
        if value:
            out[value] = html.unescape(re.sub(r"<[^>]+>", "", text)).strip()
    return out


def _parse_amount(result_html: str) -> int | None:
    """Сумма стоит прямо перед подписью «Приблизительная сумма».

    Формат переменный: 2 знака после запятой или 1 (1 знак = десятые → 50 коп.).
    Дробную часть дополняем справа до сотых, округляем до рубля.
    """
    idx = result_html.find("Приблизительная сумма")
    if idx < 0:
        return None
    before = result_html[max(0, idx - 400):idx]
    m = re.search(r"([0-9][0-9\s]*?)(?:[,.](\d{1,2}))?\s*₽[^0-9]*$", before)
    if not m:
        return None
    rub = int(re.sub(r"\D", "", m.group(1)))
    frac = int((m.group(2) or "0").ljust(2, "0")[:2])
    return rub + (1 if frac >= 50 else 0)


def _result_amount(region: str, code: str) -> int | None:
    qs = urllib.parse.urlencode({
        "provider": "pcc",
        "pcc-reason": "es",
        "pcc-region": region,
        "pcc-type": code[:2],
        "pcc-code": code,
    })
    return _parse_amount(_fetch(f"{BASE}/result?{qs}"))


async def _upsert(session, rows: list[dict]) -> None:
    stmt = pg_insert(CertPrice).values(rows)
    stmt = stmt.on_conflict_do_update(
        index_elements=["region_code", "tsr_code"],
        set_={
            "region_name": stmt.excluded.region_name,
            "tsr_name": stmt.excluded.tsr_name,
            "amount": stmt.excluded.amount,
            "updated_at": func.now(),
        },
    )
    await session.execute(stmt)
    await session.commit()


async def main() -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    regions = _parse_regions(_fetch(f"{BASE}?sct=sp"))
    only = {r.strip() for r in os.environ.get("SFR_REGIONS", "").split(",") if r.strip()}
    if only:
        regions = {k: v for k, v in regions.items() if k in only}

    # Резюмирование: пропускаем регионы, обновлённые недавно (если не SFR_FORCE).
    done: set[str] = set()
    if not os.environ.get("SFR_FORCE"):
        cutoff = datetime.now(timezone.utc) - timedelta(hours=12)
        async with async_session_maker() as s:
            done = set(
                (await s.execute(
                    select(CertPrice.region_code).where(CertPrice.updated_at >= cutoff).distinct()
                )).scalars().all()
            )
    todo = {k: v for k, v in regions.items() if k not in done}
    print(f"Всего регионов: {len(regions)}; к обработке: {len(todo)}; пропущено (свежих): {len(done)}", flush=True)

    total = 0
    async with async_session_maker() as session:
        for rcode, rname in todo.items():
            rows = []
            for code, tname in TRACKED.items():
                try:
                    amount = _result_amount(rcode, code)
                except Exception as exc:  # noqa: BLE001
                    amount = None
                    print(f"  ! {rcode}/{code}: {exc}", flush=True)
                if amount is not None:
                    rows.append({
                        "region_code": rcode, "region_name": rname,
                        "tsr_code": code, "tsr_name": tname, "amount": amount,
                    })
                await asyncio.sleep(0.3)  # вежливость к гос-серверу
            if rows:
                await _upsert(session, rows)  # запись сразу после региона
                total += len(rows)
            print(f"  {rcode} ({rname}): {len(rows)} цен — сохранено", flush=True)

    print(f"Готово: записано/обновлено {total} цен по {len(todo)} регионам.", flush=True)


if __name__ == "__main__":
    asyncio.run(main())
