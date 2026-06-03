"""Определение IP клиента, ключ для rate-limit и проверка админ-токена."""
import hmac

from fastapi import Header, HTTPException, Request, status

from .config import settings


def client_ip(request: Request) -> str:
    """Реальный IP клиента.

    Приоритет — X-Real-IP: его nginx проставляет сам ($remote_addr) и клиент
    подделать не может. X-Forwarded-For читать первым нельзя — клиент может
    подставить туда любой адрес и так обойти rate-limit.
    (Если впереди появится CDN/Cloudflare — IP клиента брать из его заголовка.)
    """
    real = request.headers.get("x-real-ip")
    if real:
        return real.strip()
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def rate_limit_key(request: Request) -> str:
    return client_ip(request)


def require_admin(x_admin_token: str = Header(default="")) -> None:
    """Защита админских эндпоинтов. Сравнение в постоянное время."""
    expected = settings.admin_token
    if not expected or not hmac.compare_digest(x_admin_token, expected):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid admin token"
        )
