FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY app ./app

# не работаем из-под root
RUN useradd -m appuser
USER appuser

EXPOSE 8000

# ВАЖНО: один worker. Rate-limit (slowapi) и кэш /api/stats держатся в памяти
# процесса — несколько воркеров их раздробят (лимит станет 5×N на воркер, счётчик
# «поплывёт»). Для масштабирования сначала вынести стейт в Redis, потом --workers.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
