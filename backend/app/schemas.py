"""Pydantic-схемы запросов/ответов."""
import re
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator


class LeadIn(BaseModel):
    """Тело POST /api/leads — то, что присылает форма с сайта."""

    form_type: Literal["quiz", "webinar", "consult"]
    name: str | None = Field(default=None, max_length=120)
    contact: str = Field(min_length=2, max_length=160)
    quiz_data: dict[str, Any] | None = None

    utm_source: str | None = Field(default=None, max_length=200)
    utm_medium: str | None = Field(default=None, max_length=200)
    utm_campaign: str | None = Field(default=None, max_length=200)
    utm_term: str | None = Field(default=None, max_length=200)
    utm_content: str | None = Field(default=None, max_length=200)
    referrer: str | None = Field(default=None, max_length=500)
    page_url: str | None = Field(default=None, max_length=500)

    # honeypot: настоящие пользователи это поле не видят и не заполняют
    company: str | None = Field(default=None, max_length=200)
    # согласие на обработку ПДн (чекбокс на форме)
    consent: bool = False

    @field_validator("contact", "name", mode="before")
    @classmethod
    def _strip(cls, v: Any) -> Any:
        return v.strip() if isinstance(v, str) else v

    @field_validator("contact")
    @classmethod
    def _valid_phone(cls, v: str) -> str:
        # Контакт принимаем только как телефон (11 цифр, ведущая 8 → 7).
        digits = re.sub(r"\D", "", v or "")
        if digits.startswith("8"):
            digits = "7" + digits[1:]
        if len(digits) != 11 or not digits.startswith("7"):
            raise ValueError("contact должен быть телефоном из 11 цифр")
        return v

    @field_validator("quiz_data")
    @classmethod
    def _clean_quiz_data(cls, v: Any) -> Any:
        # Только известные ключи квиза, значения — короткие строки.
        # Отсекает произвольные ключи/HTML-инъекции и мусорные payload'ы.
        if v is None:
            return None
        if not isinstance(v, dict):
            raise ValueError("quiz_data должен быть объектом")
        allowed = ("who", "diagnosis", "gmfcsLevel", "ipra")
        cleaned = {k: str(v[k])[:64] for k in allowed if v.get(k) is not None}
        return cleaned or None


class LeadOut(BaseModel):
    """Заявка в ответе админских эндпоинтов."""

    id: int
    user_id: int | None
    created_at: datetime
    form_type: str
    name: str | None
    contact: str
    phone: str | None
    quiz_data: dict[str, Any] | None
    # Человекочитаемые пары вопрос/ответ из справочника quiz_dictionary (для CRM)
    quiz: list[dict[str, Any]] = []
    utm_source: str | None
    utm_medium: str | None
    utm_campaign: str | None
    utm_term: str | None
    utm_content: str | None
    referrer: str | None
    page_url: str | None
    ip: str | None
    user_agent: str | None
    consent: bool

    # Статус доставки в CRM
    crm_status: str
    crm_attempts: int
    crm_next_attempt_at: datetime | None
    crm_sent_at: datetime | None
    crm_last_error: str | None
    crm_ref: str | None

    model_config = {"from_attributes": True}
