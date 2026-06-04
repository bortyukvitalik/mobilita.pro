# iprahelp.ru (Mobilita) — техническая документация проекта

**Создан:** 2026-05-28 · **Обновлён:** 2026-06-03
**Передаёт:** Андрей Тиганов → **Получает:** IT-директор

---

## Что это за проект

Лендинг-диагностика для получения ТСР (технических средств реабилитации) по
государственной программе ИПРА. Сайт бесплатный — помогает инвалидам и семьям
разобраться с оформлением ИПРА и получить ТСР через электронный сертификат СФР.
Совместно с фондом «Шагать не просто» (https://ne-prosto-fond.online/).

**Живой сайт:** https://iprahelp.ru

Поток заявки: **форма на сайте → `POST /api/leads` → PostgreSQL** (клиент дедуплицируется
по телефону) **→ фоновый воркер `crm-worker` → Bitrix24** (с ретраями).

---

## Структура папки

```
iprahelp-delivery/
├── README.md                  ← этот файл
├── docker-compose.yml         ← 4 сервиса: db + api + crm-worker + web
├── docker-compose.prod.yml    ← прод-оверлей (Caddy, авто-HTTPS)
├── .env.example               ← шаблон секретов (скопировать в .env)
│
├── site/
│   ├── index.html             ← лендинг (один файл); согласие на ПДн — в попапе (реквизиты фонда)
│   ├── favicon.svg            ← фавикон (логотип «M»)
│   ├── tailwind.css           ← СОБРАННЫЙ Tailwind (self-hosted, не CDN!)
│   └── cert_amounts.json      ← фоллбэк калькулятора (основной источник — БД)
│
├── tailwind.input.css         ← исходник Tailwind (@tailwind base/components/utilities)
│
├── backend/                   ← FastAPI + воркер CRM
│   ├── Dockerfile
│   ├── requirements.txt
│   └── app/
│       ├── main.py            ← API-эндпоинты + lifespan (сид справочника)
│       ├── models.py          ← 4 таблицы: users, leads, cert_prices, quiz_dictionary
│       ├── schemas.py         ← валидация форм (телефон, quiz_data)
│       ├── db.py              ← async-подключение к PostgreSQL
│       ├── security.py        ← honeypot, rate-limit, админ-токен (compare_digest)
│       ├── config.py          ← настройки из .env (вкл. CRM_*)
│       ├── stats.py           ← счётчики «обратились сегодня» / «получили ТСР»
│       ├── sfr_sync.py        ← парсер цен СФР (ktsr.sfr.gov.ru) → cert_prices
│       ├── quiz_catalog.py    ← сид-данные справочника квиза + резолвер кодов
│       ├── quiz_seed.py       ← наполнение таблицы quiz_dictionary
│       ├── crm_client.py      ← отправитель в CRM (заглушки + Bitrix24)
│       └── crm_dispatch.py    ← воркер очереди: claim → отправка → статусы/ретраи
│
├── nginx/
│   └── default.conf           ← статика + проксирование /api (resolver — см. ниже)
│
├── scripts/
│   ├── deploy.py              ← легаси FTP-деплой статики (reg.ru)
│   └── serve_local.py         ← быстрый статик-просмотр (без бекенда)
│
└── docs/                       ← iprahelp.md, tech.md, site-structure.md, roadmap.md,
                                  hypothesis.md, content.md
```

---

## Технический стек

| Компонент | Решение |
|-----------|---------|
| Frontend | Один HTML-файл + **self-hosted Tailwind** (`site/tailwind.css`) + Vanilla JS |
| Backend | Python 3.12 + FastAPI (async SQLAlchemy 2.0 + asyncpg) |
| База данных | PostgreSQL 16 |
| Веб-сервер | nginx (статика + прокси `/api`) |
| Очередь в CRM | отдельный воркер (`crm-worker`), доставка в Bitrix24 с ретраями |
| Оркестрация | Docker Compose — **4 контейнера**: `db`, `api`, `crm-worker`, `web` |
| Данные калькулятора | таблица `cert_prices` (парсер СФР); `cert_amounts.json` — фоллбэк |

> **Tailwind self-hosted:** новые CSS-классы в `index.html` не появятся, пока не
> пересоберёшь: `npx tailwindcss -i tailwind.input.css -o site/tailwind.css --minify`.
> (Многие правки можно делать инлайн-стилями, чтобы не пересобирать.)

---

## База данных (4 таблицы)

| Таблица | Назначение |
|---------|-----------|
| `users` | Клиент, **уникален по телефону** (без дублей). Заявок у клиента — сколько угодно. |
| `leads` | Заявки. FK `user_id`, `form_type` (quiz/webinar/consult), `quiz_data` (коды ответов), UTM, `crm_*` (статус доставки в CRM). |
| `cert_prices` | Справочник номиналов сертификата СФР: регион × ТСР → сумма. Источник — парсер. |
| `quiz_dictionary` | Справочник квиза: коды вопросов/ответов → человеческий текст (как на сайте). |

Таблицы создаются автоматически при старте (`Base.metadata.create_all`).
**Миграций (Alembic) нет** — при изменении схемы существующей таблицы нужен ручной
`ALTER TABLE` (или пересоздание БД на dev).

---

## Запуск (Docker)

```bash
cp .env.example .env            # заполнить пароли, ADMIN_TOKEN, при желании CRM_*
docker compose up -d --build    # поднимет db + api + crm-worker + web
```

- Сайт: `http://localhost/` (или `http://localhost:${WEB_PORT}/`)
- Здоровье: `curl http://localhost/api/health` → `{"status":"ok"}`
- Swagger `/docs` — **выключен** по умолчанию (включается `DOCS_ENABLED=true`).

Остановить: `docker compose down` · удалить и БД: `docker compose down -v`.

### Разовые команды (внутри контейнеров)

```bash
# Обновить цены СФР (парсер, запускать ежеквартально):
docker compose exec api python -m app.sfr_sync

# Пере-сидеть справочник квиза (после правки текстов вариантов на сайте):
docker compose exec api python -m app.quiz_seed

# Прогнать очередь в CRM вручную (one-shot, помимо авто-цикла):
docker compose exec crm-worker python -m app.crm_dispatch
```

---

## API-эндпоинты

Публичные (с сайта):

| Метод | Путь | Назначение |
|-------|------|-----------|
| GET | `/api/health` | проверка живости |
| GET | `/api/stats` | счётчики «обратились сегодня» / «семей получили ТСР» (кэш 30с) |
| GET | `/api/cert-amounts` | данные калькулятора из `cert_prices` (кэш 10 мин) |
| GET | `/api/quiz-catalog` | справочник квиза (вопросы + варианты) из `quiz_dictionary` |
| POST | `/api/leads` | приём заявки: honeypot, валидация телефона, дедуп клиента |

Админские (заголовок `X-Admin-Token: <ADMIN_TOKEN>`):

| Метод | Путь | Назначение |
|-------|------|-----------|
| GET | `/api/leads` | список заявок (+ человекочитаемый квиз `quiz`) |
| GET | `/api/users` | уникальные клиенты + число их заявок |
| GET | `/api/crm-status` | сводка очереди доставки в CRM по статусам |
| POST | `/api/leads/{id}/crm-retry` | вернуть лид в очередь (после `error`) |
| GET | `/api/leads.csv` | выгрузка в CSV (с расшифрованными ответами) |

```bash
curl -H "X-Admin-Token: ВАШ_ТОКЕН" http://localhost/api/leads
curl -H "X-Admin-Token: ВАШ_ТОКЕН" http://localhost/api/leads.csv -o leads.csv
```

---

## Доставка лидов в CRM (Bitrix24)

Заявка хранится в БД с **кодами** ответов; человекочитаемый текст подставляется из
справочника при отдаче. Фоновый сервис `crm-worker` асинхронно доставляет лиды в CRM.

**Поток статусов:** `new → sending → done` либо `retry`(с бэкоффом) `→ … → error`.

- **Бэкофф:** после 1-й ошибки +15 мин, 2-й +1 ч, 3-й +6 ч; затем `error` (всего 4 попытки).
- **Защита от двойной отправки:** `FOR UPDATE SKIP LOCKED` + промежуточный статус
  `sending` + реапер зависших (30 мин). ⚠️ Воркер держать в **одном экземпляре**.
- **Идемпотентность:** до 3 дублей при потере ответа допустимы (CRM-дедупа нет);
  в `COMMENTS` есть маркер `iprahelp_lead_id` для ручного дедупа при необходимости.
- **Режимы** (`CRM_MODE`): `off` (копим в БД) · `stub`/`stub_fail` (тест конвейера) ·
  `bitrix` (боевая отправка, нужен `CRM_WEBHOOK_URL`).

**Что уходит в Bitrix** (`crm.lead.add`): `TITLE`, `NAME`, `PHONE` (E.164),
`SOURCE_ID`, `SOURCE_DESCRIPTION`, `STATUS_ID`, `UTM_*`, и `COMMENTS` с ответами
квиза в виде «Вопрос N / Ответ N».

Подключение: задать в `.env` `CRM_MODE=bitrix` и `CRM_WEBHOOK_URL=<входящий вебхук>`,
затем `docker compose up -d crm-worker`. Проверка связи (read-only):
`{вебхук}/profile.json`.

---

## Справочники

**Квиз (`quiz_dictionary`).** Коды (`who`, `diagnosis`, `gmfcsLevel`, `ipra` и их
варианты) → текст «как на сайте». Источник текстов — `quiz_catalog.py` (сид).
Сидится при первом старте; правки в БД не затираются. Обновить из кода:
`python -m app.quiz_seed`. У GMFCS две шкалы на кодах 1–5 (дети «GMFCS I–V»,
взрослые «Уровень А–Д») — различаются полем `context`.

**Цены СФР (`cert_prices`).** Парсер `sfr_sync.py` обходит `ktsr.sfr.gov.ru`
(89 регионов × 10 ТСР), пишет per-region (устойчив к обрыву, резюмируется).
Запуск ежеквартально: `python -m app.sfr_sync`.

**Счётчики (`stats.py`).** «Обратились сегодня» — `simulated` (имитация по МСК-времени)
или `real` (из БД), переключатель `STATS_MODE`. «Семей получили ТСР» = `STATS_BASELINE`
(1000) + число заявок.

---

## Переменные окружения (.env)

| Переменная | Назначение |
|-----------|-----------|
| `POSTGRES_USER/PASSWORD/DB` | креды PostgreSQL |
| `ADMIN_TOKEN` | токен админ-эндпоинтов (**≥16 симв.**, иначе API не стартует) |
| `ALLOWED_ORIGINS` | домены для CORS |
| `RATE_LIMIT` | лимит `/api/leads` с одного IP (напр. `1/second`) |
| `STATS_MODE` | `simulated` \| `real` |
| `STATS_BASELINE` | база счётчика «получили ТСР» (1000) |
| `DOCS_ENABLED` | Swagger `/docs` (на проде `false`) |
| `WEB_PORT` | порт сайта на хосте (прод — 80) |
| `CRM_MODE` | `off` \| `stub` \| `stub_fail` \| `bitrix` |
| `CRM_WEBHOOK_URL` | входящий вебхук Bitrix24 (**секрет**) |
| `CRM_BATCH_SIZE` | размер пачки за прогон (50) |
| `CRM_STATUS_ID` | STATUS_ID нового лида (напр. `UC_RYNCPM`) |
| `CRM_SOURCE_ID` | SOURCE_ID (напр. `UC_IPRA_PROJECT`) |
| `CRM_SOURCE_DESCRIPTION` | описание источника |
| `CRM_TITLE_PREFIX` | префикс заголовка лида |
| `FTP_*` | легаси-деплой статики на reg.ru |

> **Секреты в репозиторий не коммитятся** — только в `.env` (он в `.gitignore`).

---

## Прод на VPS

Рекомендованная конфигурация под ~1–2к польз./день: **2 vCPU / 4 ГБ RAM / 50 ГБ NVMe**,
дата-центр **в РФ** (152-ФЗ: телефоны + данные о здоровье = спецкатегория ПДн).

1. Ubuntu 22.04/24.04 LTS + Docker, склонировать проект, создать боевой `.env`
   (сменить `POSTGRES_PASSWORD` и `ADMIN_TOKEN`, задать `CRM_*`).
2. `docker compose up -d --build`.
3. **HTTPS:** `docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d`
   (Caddy выдаёт сертификат Let's Encrypt). Домен `iprahelp.ru` → A-запись на IP.
4. **Бэкапы:** включить у провайдера + желательно `pg_dump` по крону (логический дамп БД).

> **nginx + Docker:** `/api` проксируется через переменную с `resolver 127.0.0.11`,
> поэтому пересборка `api`-контейнера (новый IP) **не роняет** `/api` — nginx
> перерезолвит сам, рестарт `web` не нужен.

---

## Структура сайта (секции)

HERO · PATHS (3 сценария) · STATS (статистика, миссия фонда) · QUIZ (4 шага +
WOW-момент + результат) · HOW (5 шагов) · CASES (карусель кейсов) · CALC
(калькулятор СФР) · NOVICE (для тех, у кого нет ИПРА) · WEBINAR · FAQ · CONSULT (форма).

Формы (`submitForm` / `submitWebinar` / `submitConsult`) шлют `POST /api/leads` через
общий `sendLead()` (UTM-контекст + honeypot). Ответы квиза хранятся в localStorage и
прикрепляются к **любой** заявке.

---

## Социальные каналы

| Канал | Ссылка |
|-------|--------|
| Telegram | https://t.me/mobilita_help |
| ВКонтакте | https://vk.com/mobilita |
| Макс | https://max.ru/mobilita_help |

---

## Что осталось / на будущее

- **Опубликовать полную Политику обработки ПДн** — сейчас на сайте только текст согласия
  (попап с реквизитами фонда), отдельной страницы политики нет. Юрист + регистрация
  оператора ПДн в Роскомнадзоре.
- **Alembic-миграции** — сейчас схема создаётся `create_all`, изменения существующих
  таблиц делаются вручную `ALTER TABLE`.
- **Сменить FTP-пароль reg.ru**, если когда-либо передавался открытым текстом.
- (Опционально) Яндекс.Метрика и цели на шаги квиза; расширение каталога ТСР.

**Сделано в этой версии:** бекенд + БД, дедуп клиентов, справочники (квиз + цены СФР),
калькулятор из БД, счётчики на бекенде, **очередь доставки лидов в Bitrix24 с ретраями**,
self-hosted Tailwind, фавикон, security-аудит (CSP, заголовки, хардненинг Docker).
