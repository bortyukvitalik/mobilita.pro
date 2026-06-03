"""Настройки приложения — читаются из переменных окружения (.env)."""
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Подключение к PostgreSQL (async-драйвер asyncpg)
    database_url: str = "postgresql+asyncpg://iprahelp:iprahelp@db:5432/iprahelp"

    # Токен для доступа к выгрузке заявок (заголовок X-Admin-Token)
    admin_token: str = "change-me"

    # Разрешённые источники для CORS (через запятую). Сайт ходит на тот же домен,
    # поэтому в норме CORS не нужен, но оставляем настраиваемым.
    allowed_origins: str = "https://iprahelp.ru,https://www.iprahelp.ru"

    # Лимит на отправку заявок с одного IP
    rate_limit: str = "1/second"

    # Счётчик «обратились сегодня»: simulated (имитация по времени) | real (из БД)
    stats_mode: str = "simulated"

    # Swagger /docs — по умолчанию выключен (включать только локально через DOCS_ENABLED=true)
    docs_enabled: bool = False

    # База для счётчика «семей получили ТСР» = stats_baseline + кол-во заявок
    stats_baseline: int = 1000

    # ─── Отправка лидов в CRM (очередь + ретраи) ───
    # off    — воркер ничего не делает (лиды копятся в статусе new);
    # stub   — тестовый отправитель: имитирует успех (проверить конвейер без CRM);
    # stub_fail — тестовый отправитель: всегда ошибка (проверить ретраи/error);
    # bitrix — реальная отправка в Bitrix24 (нужен crm_webhook_url).
    crm_mode: str = "off"
    # Входящий вебхук Bitrix24, напр. https://xxx.bitrix24.ru/rest/1/xxxxxxxx/
    crm_webhook_url: str = ""
    # Размер пачки за один прогон воркера
    crm_batch_size: int = 50
    # Поля лида в Bitrix24 (crm.lead.add)
    crm_status_id: str = ""                              # STATUS_ID (напр. UC_RYNCPM); пусто = не слать
    crm_source_id: str = "UC_IPRA_PROJECT"               # SOURCE_ID
    crm_source_description: str = "Отдельный лендинг"     # SOURCE_DESCRIPTION
    crm_title_prefix: str = "Лендинг Эрготерапевт"        # префикс TITLE: «<prefix>: <телефон>»

    @property
    def origins_list(self) -> list[str]:
        return [o.strip() for o in self.allowed_origins.split(",") if o.strip()]


settings = Settings()
