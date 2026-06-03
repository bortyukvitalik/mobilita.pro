# iprahelp.ru — техническая документация

---

## Файлы проекта

| Путь | Описание |
|------|----------|
| `/Users/andrejtiganov/Desktop/AI agent/mobilita/index.html` | Основной файл сайта (~163 КБ) |
| `/Users/andrejtiganov/Desktop/AI agent/mobilita/cert_amounts.json` | Данные калькулятора (890 строк, СФР по регионам) |
| `/Users/andrejtiganov/Desktop/AI agent/serve.py` | Локальный сервер (порт 7771) |

---

## Стек

| Компонент | Решение |
|-----------|---------|
| CSS-фреймворк | Tailwind CSS (CDN) |
| JS | Vanilla JS (без фреймворков) |
| Шрифты | Google Fonts (Inter) |
| Иконки | Emoji + inline SVG |
| Данные | cert_amounts.json (inline fetch) |

Всё в одном `index.html` — намеренно, для простоты деплоя и тестирования.

---

## Хостинг и деплой

⚠️ **Секреты больше не хранятся в репозитории.** Все доступы (FTP, БД, токен)
лежат в файле `.env` в корне проекта (см. `.env.example`), который не коммитится.
Если старый FTP-пароль когда-либо был в открытом виде — его нужно сменить в ЛК reg.ru.

| Параметр | Значение |
|----------|---------|
| Хостинг (легаси, статика) | reg.ru, `server295.hosting.reg.ru`, FTP порт 21 |
| Логин / пароль FTP | в `.env` (`FTP_USER` / `FTP_PASS`) |
| Удалённая папка | `/www/iprahelp.ru` (`FTP_REMOTE`) |
| Прод (новое) | VPS с Docker — см. `README.md` и `docker-compose.yml` |

### Деплой статики (легаси reg.ru)

```bash
python3 scripts/deploy.py   # креды читаются из .env, не из кода
```

### Деплой полного стека (VPS + Docker)

```bash
docker compose up -d --build   # nginx + FastAPI + PostgreSQL
```

---

## Локальный сервер

```bash
cd "/Users/andrejtiganov/Desktop/AI agent"
python serve.py
# → http://localhost:7771/mobilita/index.html
```

---

## Работа с секциями (Python-скрипт реорганизации)

При необходимости менять порядок секций — скрипт читает маркеры `<!-- ═══ ИМЯ ═══ -->`, нарезает файл на именованные куски, собирает в новом порядке.

```python
# Пример вызова
markers = {
    'HERO': '<!-- ═══ HERO ═══ -->',
    'QUIZ': '<!-- ═══ QUIZ ═══ -->',
    # ...
}
new_order = ['HERO', 'PATHS', 'STATS', 'QUIZ', 'HOW', 'CASES', 'CALC', 'NOVICE', 'WEBINAR', 'FAQ', 'CONSULT', 'FOOTER', 'TG', 'JS']
```

---

## Интеграции (планируется)

| Сервис | Статус | Описание |
|--------|--------|----------|
| Яндекс Метрика | ⏳ Планируется | Трекинг конверсий квиза |
| Битрикс24 | ⏳ Планируется | Передача лидов из формы |
| Telegram Bot API | ⏳ Планируется | Уведомления о новых лидах |

---

## Известные технические решения

- **Карусель кейсов:** CSS `overflow-x-auto` + `scroll-snap-type: x mandatory` + `scroll-snap-align: start`
- **Квиз:** Vanilla JS, состояние в объекте, переключение `div.hidden/block`
- **GMFCS-бейдж:** всегда скрыт (`gmfcsBadge.style.display='none'`)
- **Калькулятор:** `fetch('cert_amounts.json')` → фильтрация по региону и категории
- **Dropdown dedup:** `populateDropdown()` без дублирующих пустых опций

---

## Будущая архитектура (в рамках Mobilita)

iprahelp.ru → станет модулем Mobilita (B2C-блок «Диагностика ИПРА»). Сейчас работает как самостоятельный MVP для тестирования гипотезы.
