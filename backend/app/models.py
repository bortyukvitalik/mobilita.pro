"""ORM-модели. Одна таблица — заявки (leads)."""
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, UniqueConstraint, func, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class User(Base):
    """Клиент — уникален по номеру телефона. Заявок (Lead) у клиента может быть много."""

    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    phone: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    consent: Mapped[bool] = mapped_column(default=False, server_default=text("false"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class Lead(Base):
    __tablename__ = "leads"

    id: Mapped[int] = mapped_column(primary_key=True)
    # клиент (уникален по телефону); у одного клиента заявок может быть много
    user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True, nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )

    # quiz | webinar | consult
    form_type: Mapped[str] = mapped_column(String(20), index=True)

    name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    contact: Mapped[str] = mapped_column(String(160))
    # Нормализованный номер телефона (только цифры, напр. 79991234567)
    phone: Mapped[str | None] = mapped_column(String(32), index=True, nullable=True)

    # Ответы квиза (who/diagnosis/gmfcsLevel/ipra) — коды вариантов.
    # Человеческий текст не храним в лиде: маппим из справочника quiz_dictionary при отдаче в CRM.
    quiz_data: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    # Источник трафика
    utm_source: Mapped[str | None] = mapped_column(String(200), nullable=True)
    utm_medium: Mapped[str | None] = mapped_column(String(200), nullable=True)
    utm_campaign: Mapped[str | None] = mapped_column(String(200), nullable=True)
    utm_term: Mapped[str | None] = mapped_column(String(200), nullable=True)
    utm_content: Mapped[str | None] = mapped_column(String(200), nullable=True)
    referrer: Mapped[str | None] = mapped_column(String(500), nullable=True)
    page_url: Mapped[str | None] = mapped_column(String(500), nullable=True)

    # Техническая метаинформация
    ip: Mapped[str | None] = mapped_column(String(64), nullable=True)
    user_agent: Mapped[str | None] = mapped_column(String(400), nullable=True)

    # Согласие на обработку ПДн (152-ФЗ)
    consent: Mapped[bool] = mapped_column(default=False, server_default=text("false"))

    # ─── Доставка лида в CRM (очередь + ретраи). Это статус ДОСТАВКИ, не воронки продаж. ───
    # new → sending → done | retry → … → error
    crm_status: Mapped[str] = mapped_column(
        String(16), index=True, server_default=text("'new'")
    )
    crm_attempts: Mapped[int] = mapped_column(default=0, server_default=text("0"))
    # Когда лид снова можно попытаться отправить (бэкофф). NULL = можно сразу.
    crm_next_attempt_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), index=True, nullable=True
    )
    crm_last_attempt_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    crm_sent_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    crm_last_error: Mapped[str | None] = mapped_column(String(500), nullable=True)
    # ID лида на стороне CRM (для трассировки), если CRM его вернула
    crm_ref: Mapped[str | None] = mapped_column(String(64), nullable=True)


class CertPrice(Base):
    """Справочник номиналов сертификата СФР: регион × ТСР → сумма. Источник ktsr.sfr.gov.ru."""

    __tablename__ = "cert_prices"
    __table_args__ = (UniqueConstraint("region_code", "tsr_code", name="uq_cert_region_tsr"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    region_code: Mapped[str] = mapped_column(String(16), index=True)
    region_name: Mapped[str] = mapped_column(String(120))
    tsr_code: Mapped[str] = mapped_column(String(16), index=True)
    tsr_name: Mapped[str] = mapped_column(String(200))
    amount: Mapped[int] = mapped_column()
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class QuizDictionary(Base):
    """Справочник квиза: вопросы и варианты ответов человеческим текстом (как на сайте).

    type='question' — текст вопроса (code = идентификатор вопроса: who/diagnosis/...).
    type='answer'   — текст варианта ответа (code = код варианта: child/dcp/5/check...).
    field   — к какому вопросу относится строка.
    context — '' обычно; 'child'/'adult' для GMFCS (две шкалы на кодах 1–5).
    При отдаче лида в CRM коды из quiz_data сопоставляются с этой таблицей.
    """

    __tablename__ = "quiz_dictionary"
    __table_args__ = (
        UniqueConstraint("field", "type", "code", "context", name="uq_quiz_dict"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    field: Mapped[str] = mapped_column(String(32), index=True)
    type: Mapped[str] = mapped_column(String(16), index=True)  # question | answer
    code: Mapped[str] = mapped_column(String(64), index=True)
    context: Mapped[str] = mapped_column(String(16), server_default=text("''"))
    label: Mapped[str] = mapped_column(String(200))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
