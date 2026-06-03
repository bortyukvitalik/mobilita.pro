"""
Легаси-деплой статики iprahelp.ru на shared-хостинг reg.ru по FTP.

⚠️  При переезде на VPS с Docker этот скрипт больше не нужен —
    сайт раздаётся nginx-контейнером (см. docker-compose.yml).
    Оставлен на случай, если статика временно ещё живёт на reg.ru.

Креды берутся из окружения или из файла .env в корне проекта
(НЕ из кода — см. .env.example). Запуск:
    python3 scripts/deploy.py
"""
import ftplib
import os
import sys

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT_DIR = os.path.join(SCRIPT_DIR, "..")
SITE_DIR = os.path.join(ROOT_DIR, "site")

FILES_TO_DEPLOY = ["index.html", "cert_amounts.json"]


def load_dotenv(path: str) -> None:
    """Минимальный парсер .env без внешних зависимостей."""
    if not os.path.exists(path):
        return
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            os.environ.setdefault(key.strip(), value.strip())


def deploy() -> None:
    load_dotenv(os.path.join(ROOT_DIR, ".env"))

    host = os.environ.get("FTP_HOST")
    user = os.environ.get("FTP_USER")
    password = os.environ.get("FTP_PASS")
    remote = os.environ.get("FTP_REMOTE", "/www/iprahelp.ru")

    if not all([host, user, password]):
        sys.exit(
            "Не заданы FTP_HOST / FTP_USER / FTP_PASS. "
            "Скопируйте .env.example в .env и заполните."
        )

    print(f"Подключаюсь к {host}...")
    ftp = ftplib.FTP()
    ftp.connect(host, 21, timeout=30)
    ftp.login(user, password)
    ftp.cwd(remote)
    print(f"Папка: {remote}")

    for filename in FILES_TO_DEPLOY:
        local_path = os.path.join(SITE_DIR, filename)
        if not os.path.exists(local_path):
            print(f"  ⚠️  Файл не найден: {local_path}")
            continue
        size = os.path.getsize(local_path)
        with open(local_path, "rb") as f:
            ftp.storbinary(f"STOR {filename}", f)
        print(f"  ✅ {filename} ({size:,} байт)")

    ftp.quit()
    print("Деплой завершён! Сайт: https://iprahelp.ru")


if __name__ == "__main__":
    deploy()
