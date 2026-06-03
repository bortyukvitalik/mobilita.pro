"""Наполнение справочника quiz_dictionary из сид-данных (app.quiz_catalog).

Старт приложения вызывает seed_if_empty() — наполняет таблицу при первом запуске,
не затирая правки, сделанные руками в БД.

Ручное обновление после изменения текстов на сайте (перезапишет подписи из кода):
    docker compose exec api python -m app.quiz_seed
"""
import asyncio

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from .db import async_session_maker, engine
from .models import Base, QuizDictionary
from .quiz_catalog import seed_rows


async def load_maps(session) -> tuple[dict, dict]:
    """Справочник из БД → (questions {field: label}, answers {(field, context, code): label})."""
    rows = (await session.execute(select(QuizDictionary))).scalars().all()
    questions: dict = {}
    answers: dict = {}
    for r in rows:
        if r.type == "question":
            questions[r.field] = r.label
        else:
            answers[(r.field, r.context or "", r.code)] = r.label
    return questions, answers


async def seed_if_empty(session) -> int:
    """Наполнить таблицу при первом запуске. Идемпотентно: on_conflict_do_nothing,
    поэтому одновременный старт api и crm-worker не падает на гонке (IntegrityError)."""
    count = (await session.execute(select(func.count()).select_from(QuizDictionary))).scalar_one()
    if count:
        return 0
    rows = seed_rows()
    stmt = pg_insert(QuizDictionary).values(rows).on_conflict_do_nothing(
        index_elements=["field", "type", "code", "context"]
    )
    await session.execute(stmt)
    await session.commit()
    return len(rows)


async def reseed(session) -> int:
    """Принудительно обновить подписи из кода (upsert по field+type+code+context)."""
    rows = seed_rows()
    stmt = pg_insert(QuizDictionary).values(rows)
    stmt = stmt.on_conflict_do_update(
        index_elements=["field", "type", "code", "context"],
        set_={"label": stmt.excluded.label, "updated_at": func.now()},
    )
    await session.execute(stmt)
    await session.commit()
    return len(rows)


async def main() -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with async_session_maker() as session:
        n = await reseed(session)
    print(f"Справочник quiz_dictionary обновлён: {n} строк.", flush=True)


if __name__ == "__main__":
    asyncio.run(main())
