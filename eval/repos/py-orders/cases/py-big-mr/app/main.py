# Copyright (c) 2026 Acme Commerce GmbH
# SPDX-License-Identifier: Apache-2.0

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.api import admin, health, orders, payments, products
from app.core.config import get_settings
from app.core.errors import DomainError
from app.core.logging import get_logger, setup_logging

log = get_logger(__name__)


def create_app() -> FastAPI:
    settings = get_settings()
    setup_logging(settings)
    app = FastAPI(title="py-orders", version="0.14.2")

    @app.exception_handler(DomainError)
    async def handle_domain_error(request: Request, exc: DomainError) -> JSONResponse:
        if exc.status_code >= 500:
            log.warning("request_failed_upstream", path=request.url.path, code=exc.code, error=exc.message)
        return JSONResponse(
            status_code=exc.status_code,
            content={"error": {"code": exc.code, "message": exc.message, "details": exc.details}},
        )

    for module in (health, orders, payments, products, admin):
        app.include_router(module.router)
    return app


app = create_app()
