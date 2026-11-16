from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routers import assets, assignments, auth, employees, health, warranty
from app.core.config import Settings, get_settings
from app.core.errors import register_exception_handlers
from app.core.logging import configure_logging
from app.integrations.notifier import StubNotifier
from app.integrations.warranty_client import StubWarrantyClient
from app.middleware.request_context import (
    PROCESS_TIME_HEADER,
    REQUEST_ID_HEADER,
    RequestContextMiddleware,
    UnhandledErrorMiddleware,
)

TAGS = [
    {
        "name": "Auth",
        "description": "Sign in and get a bearer token. Everything else except Health needs it.",
    },
    {"name": "Employees", "description": "People who can hold equipment. Changes are admin only."},
    {
        "name": "Assets",
        "description": "IT equipment records, with filtering, search and paging. Changes are admin only.",
    },
    {
        "name": "Assignments",
        "description": "Hand an asset to an employee, record its return, and see its "
        "history. Staff and admin.",
    },
    {"name": "Warranty", "description": "Bulk warranty lookup against the external warranty source."},
    {"name": "Health", "description": "Liveness check for monitoring and the container healthcheck."},
]


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(settings.log_level)

    app = FastAPI(
        title=settings.app_name,
        version=settings.app_version,
        description="Tracks company IT equipment and who holds it. "
        'Errors share one shape: `{"error": {code, message, rule?, request_id}}`.',
        openapi_tags=TAGS,
    )

    app.state.notifier = StubNotifier(delay=settings.notifier_delay_seconds)
    app.state.warranty_client = StubWarrantyClient(delay=settings.warranty_delay_seconds)

    # Added innermost first. Order on the way in:
    # RequestContext -> CORS -> UnhandledError -> routes
    app.add_middleware(UnhandledErrorMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=False,  # bearer tokens, no cookies
        allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type", REQUEST_ID_HEADER],
        expose_headers=[REQUEST_ID_HEADER, PROCESS_TIME_HEADER],
    )
    app.add_middleware(RequestContextMiddleware)

    register_exception_handlers(app)

    for router in (
        auth.router,
        employees.router,
        assets.router,
        assignments.router,
        warranty.router,
        health.router,
    ):
        app.include_router(router)

    return app


app = create_app()
