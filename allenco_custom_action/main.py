"""Allen & Co Glean Custom Action API.

Run with:
    uvicorn main:app --reload

Reads DB credentials from ../.env (project root) automatically. Answers live
queries from the Glean assistant against the read-only EMS views on the Azure
SQL Managed Instance (/metadata, /query, /aggregate).
"""

import logging
import traceback
from contextlib import asynccontextmanager

from dependencies import verify_api_key
from fastapi import Depends, FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from notifications_setup import ErrorType, build_api_notifier, notify
from permissions import (
    load_superuser_emails,
    load_view_permissions_all_access,
    load_view_permissions_cache,
)
from routers import aggregate, metadata, query
from settings import load_api_key, load_db_settings, load_max_rows

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Build the notifier first so a misconfigured startup can still be reported.
    app.state.notifier = build_api_notifier()
    try:
        app.state.db_settings = load_db_settings()
        app.state.max_rows = load_max_rows()
        app.state.api_key = load_api_key()
        # View access: all-access mode (VIEW_PERMISSIONS_ALL_ACCESS) or the SQL
        # permissions view (see permissions.py). No DB connection needed at startup
        # (the cache is empty in all-access mode); each request opens its own pooled
        # connection on demand.
        app.state.view_perm_cache = load_view_permissions_cache()
        app.state.view_perm_all_access = load_view_permissions_all_access()
        app.state.superuser_emails = load_superuser_emails()
    except Exception as exc:
        notify(
            app.state.notifier,
            ErrorType.API_STARTUP,
            str(exc),
            detail=traceback.format_exc(),
        )
        raise

    logger.info(
        "Startup complete — DB: %s/%s (auth=%s, schema=%s), MAX_ROWS: %d, "
        "all_access: %s, superusers: %d",
        app.state.db_settings.server,
        app.state.db_settings.database,
        app.state.db_settings.auth_mode,
        app.state.db_settings.schema,
        app.state.max_rows,
        app.state.view_perm_all_access,
        len(app.state.superuser_emails),
    )
    yield


app = FastAPI(
    title="Allen & Co Glean Custom Action API",
    description=(
        "Glean Custom Action backend — explore the EMS schema and query the "
        "read-only EMS views on demand against the Azure SQL Managed Instance."
    ),
    version="0.1.0",
    lifespan=lifespan,
    dependencies=[Depends(verify_api_key)],
)


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    # Return 400 instead of FastAPI's default 422 for request validation errors.
    return JSONResponse(status_code=400, content={"detail": exc.errors()})


@app.get("/health", tags=["health"])
def health() -> dict[str, str]:
    """Liveness/readiness probe — unauthenticated (see dependencies._PUBLIC_PATHS).

    Cheap by design: does not touch the database (a DB blip must not cycle the
    container). Returns 200 while the process is up.
    """
    return {"status": "ok"}


app.include_router(metadata.router)
app.include_router(query.router)
app.include_router(aggregate.router)
