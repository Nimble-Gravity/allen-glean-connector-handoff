"""FastAPI dependency callables that read from app.state."""

from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from settings import DbSettings

_bearer = HTTPBearer(auto_error=False)


def get_db_settings(request: Request) -> DbSettings:
    return request.app.state.db_settings


def get_max_rows(request: Request) -> int:
    return request.app.state.max_rows


def get_notifier(request: Request):
    """Return the error notifier built at app startup."""
    return request.app.state.notifier


def get_view_perm_cache(request: Request) -> dict[str, list[str]]:
    return request.app.state.view_perm_cache


def get_superuser_emails(request: Request) -> frozenset[str]:
    return request.app.state.superuser_emails


def get_all_access(request: Request) -> bool:
    """Whether all-access mode is on (every user may query every view)."""
    return request.app.state.view_perm_all_access


# Unauthenticated paths (health/liveness probes) — the platform, not Glean, calls
# these, so they must not require the bearer key.
_PUBLIC_PATHS = frozenset({"/health"})


def verify_api_key(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> None:
    if request.url.path in _PUBLIC_PATHS:
        return
    token = credentials.credentials if credentials else None
    if token != request.app.state.api_key:
        raise HTTPException(status_code=401, detail="Invalid or missing API key")
