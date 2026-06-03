"""Справочник квиза в БД: таблица quiz_dictionary (code, type, label, ...).

Здесь лежат СИД-данные (тексты вопросов и вариантов ответов 1:1 как на сайте)
и логика сопоставления кодов → человеческий текст.

Источник правды по текстам — лендинг (site/index.html). Если поменяли тексты
вариантов на сайте — поправьте здесь и пере-сидните таблицу:
    docker compose exec api python -m app.quiz_seed

Зачем поля field и context (сверх code/type/label):
  * field   — к какому вопросу относится ответ (who/diagnosis/gmfcsLevel/ipra);
  * context — у GMFCS две шкалы на одних кодах 1–5: дети «GMFCS I–V», взрослые
              «Уровень А–Д». Для остальных вопросов context = "".
"""

# ─── СИД: вопросы (type=question). code = идентификатор вопроса (= ключ в quiz_data) ───
QUESTIONS = {
    "who": "Кому нужна помощь",
    "diagnosis": "Диагноз",
    "gmfcsLevel": "Уровень двигательных возможностей",
    "ipra": "Статус ИПРА",
}
FIELD_ORDER = ("who", "diagnosis", "gmfcsLevel", "ipra")

# ─── СИД: ответы (type=answer), сгруппированы по вопросу и контексту ───
ANSWERS = {
    # field: { context: { code: label } }
    "who": {"": {
        "child": "Ребёнок с инвалидностью или ОВЗ",
        "relative": "Взрослый родственник",
        "self": "Себе",
    }},
    "diagnosis": {"": {
        "dcp": "ДЦП",
        "sma": "СМА",
        "neuro": "Неврология / аутизм",
        "trauma_child": "Ортопедия / травма",
        "stroke": "Инсульт / ОНМК",
        "amputation": "Ампутация",
        "spine": "Травма позвоночника",
        "other_adult": "Другое",
    }},
    "gmfcsLevel": {
        "child": {
            "1": "GMFCS I — Ходит самостоятельно",
            "2": "GMFCS II — Ходит с ограничениями",
            "3": "GMFCS III — Ходит с ходунками или костылями",
            "4": "GMFCS IV — Коляска, может стоять с поддержкой",
            "5": "GMFCS V — Полная зависимость от коляски",
        },
        "adult": {
            "1": "Уровень А — Ходит самостоятельно",
            "2": "Уровень Б — Ходит с тростью или костылями",
            "3": "Уровень В — Ходит с ходунками",
            "4": "Уровень Г — В основном в коляске",
            "5": "Уровень Д — Полностью в коляске",
        },
    },
    "ipra": {"": {
        "check": "Есть — хочу проверить что всё правильно",
        "yes": "Есть ИПРА — готов оформлять ТСР",
        "no": "Нет ИПРА — только предстоит оформить",
        "unknown": "Не знаю что это",
    }},
}


def seed_rows() -> list[dict]:
    """Плоский список строк для таблицы quiz_dictionary (вопросы + ответы)."""
    rows: list[dict] = []
    for field, label in QUESTIONS.items():
        rows.append({"field": field, "type": "question", "code": field, "context": "", "label": label})
    for field, by_ctx in ANSWERS.items():
        for context, by_code in by_ctx.items():
            for code, label in by_code.items():
                rows.append({"field": field, "type": "answer", "code": code, "context": context, "label": label})
    return rows


def _gmfcs_context(who: str) -> str:
    return "adult" if who in ("relative", "self") else "child"


def resolve(quiz_data: dict | None, questions: dict, answers: dict) -> list[dict]:
    """Коды ответов → [{field, code, question, answer}] в фиксированном порядке.

    questions: {field: label}                  (строки type=question из БД)
    answers:   {(field, context, code): label} (строки type=answer из БД)
    Неизвестный код отдаём как есть — чтобы ничего не потерять.
    """
    if not quiz_data:
        return []
    out = []
    for field in FIELD_ORDER:
        val = quiz_data.get(field)
        if val is None or str(val) == "":
            continue
        code = str(val)
        context = _gmfcs_context(str(quiz_data.get("who") or "")) if field == "gmfcsLevel" else ""
        out.append({
            "field": field,
            "code": code,
            "question": questions.get(field, field),
            "answer": answers.get((field, context, code), code),
        })
    return out
