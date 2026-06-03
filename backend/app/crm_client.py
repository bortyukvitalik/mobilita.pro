"""Отправитель лида в CRM. Подключаемый: сейчас заглушка, позже — Bitrix24.

Режимы (settings.crm_mode):
  off        — не используется (воркер до отправки даже не доходит);
  stub       — имитация успешной отправки (проверить конвейер очереди без CRM);
  stub_fail  — имитация ошибки (проверить ретраи и переход в error);
  bitrix     — реальная отправка в Bitrix24 через входящий вебхук.

Исключения:
  CRMNotConfigured — режим требует настройки, которой нет (например, bitrix без URL).
                     Воркер НЕ считает это попыткой (не жжёт ретраи) и просто пропускает.
  CRMError         — отправка не удалась (сеть/ответ CRM). Воркер ретраит по бэкоффу.
"""
import asyncio
import json
import urllib.error
import urllib.request

from .config import settings


class CRMNotConfigured(Exception):
    """CRM не настроена для текущего режима — отправлять нечем."""


class CRMError(Exception):
    """Ошибка отправки в CRM — лид уйдёт в retry."""


def _phone_e164(phone: str | None) -> str:
    """79991234567 → +79991234567 (как ожидает Bitrix)."""
    p = (phone or "").strip()
    return f"+{p}" if p and not p.startswith("+") else p


def build_comments(lead, quiz: list[dict]) -> str:
    """Поле COMMENTS в Bitrix: ответы квиза в формате «Вопрос N / Ответ N» + футер.

    Доставка at-least-once: при потере ответа CRM лид уйдёт в retry и может быть
    отправлен повторно (до 4 раз). Маркер iprahelp_lead_id в футере — стабильный ключ
    (можно дедуплицировать на стороне CRM при желании).
    """
    blocks = [
        f"Вопрос {i}: {qa['question']}\nОтвет {i}: {qa['answer']}"
        for i, qa in enumerate(quiz, 1)
    ]
    footer = [f"iprahelp_lead_id={lead.id}", f"Форма: {lead.form_type}"]
    utm = [
        f"{k}={getattr(lead, 'utm_' + k)}"
        for k in ("source", "medium", "campaign", "term", "content")
        if getattr(lead, "utm_" + k, None)
    ]
    if utm:
        footer.append("UTM: " + ", ".join(utm))
    if lead.page_url:
        footer.append(f"Страница: {lead.page_url}")
    footer_text = "\n".join(footer)
    body = "\n\n".join(blocks)
    return f"{body}\n\n———\n{footer_text}" if body else footer_text


def build_bitrix_fields(lead, quiz: list[dict]) -> dict:
    """Поля для метода crm.lead.add Bitrix24."""
    title_tail = _phone_e164(lead.phone) or lead.name or f"#{lead.id}"
    fields = {
        "TITLE": f"{settings.crm_title_prefix}: {title_tail}",
        "NAME": lead.name or "",
        "SOURCE_ID": settings.crm_source_id,
        "SOURCE_DESCRIPTION": settings.crm_source_description,
        "COMMENTS": build_comments(lead, quiz),
        "PHONE": [{"VALUE": _phone_e164(lead.phone), "VALUE_TYPE": "MOBILE"}],
    }
    if settings.crm_status_id:
        fields["STATUS_ID"] = settings.crm_status_id
    if lead.utm_source:
        fields["UTM_SOURCE"] = lead.utm_source
    if lead.utm_medium:
        fields["UTM_MEDIUM"] = lead.utm_medium
    if lead.utm_campaign:
        fields["UTM_CAMPAIGN"] = lead.utm_campaign
    return fields


def _post_bitrix(lead, quiz: list[dict]) -> str:
    """Синхронный POST в Bitrix24 (вызывается из потока). Возвращает ID лида в CRM."""
    base = settings.crm_webhook_url.rstrip("/")
    url = f"{base}/crm.lead.add.json"
    body = json.dumps({
        "fields": build_bitrix_fields(lead, quiz),
        "params": {"REGISTER_SONET_EVENT": "Y"},
    }).encode("utf-8")
    req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            data = json.loads(resp.read().decode("utf-8", "replace"))
    except urllib.error.HTTPError as e:
        raise CRMError(f"Bitrix HTTP {e.code}: {e.read()[:200]!r}") from e
    except Exception as e:  # noqa: BLE001 — сеть/таймаут/парсинг
        raise CRMError(f"Bitrix запрос не удался: {e}") from e
    if "error" in data:
        raise CRMError(f"Bitrix error: {data.get('error')} {data.get('error_description', '')}")
    result = data.get("result")
    if not result:
        raise CRMError(f"Bitrix вернул пустой result: {data}")
    return str(result)


async def send_lead(lead, quiz: list[dict]) -> str:
    """Отправить лид в CRM. Вернуть ID на стороне CRM. Бросить CRMError при сбое."""
    mode = settings.crm_mode
    if mode == "stub":
        return f"stub-{lead.id}"
    if mode == "stub_fail":
        raise CRMError("stub_fail: имитация ошибки CRM")
    if mode == "bitrix":
        if not settings.crm_webhook_url:
            raise CRMNotConfigured("crm_mode=bitrix, но crm_webhook_url не задан")
        # urllib синхронный — уводим в поток, чтобы не блокировать event loop
        return await asyncio.to_thread(_post_bitrix, lead, quiz)
    raise CRMNotConfigured(f"Неизвестный crm_mode={mode!r}")
