from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from slowapi.errors import RateLimitExceeded

from api.routes.analytics import router as analytics_router
from api.routes.identity import router as identity_router
from api.routes.settlement import router as settlement_router
from app.rate_limiter import limiter


def rate_limit_exceeded_handler(request: Request, exc: RateLimitExceeded) -> JSONResponse:
    return JSONResponse(status_code=429, content={"detail": "Rate limit exceeded. Please slow down."})


def create_app() -> FastAPI:
    app = FastAPI(title="SusuCircle API")
    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, rate_limit_exceeded_handler)

    app.include_router(settlement_router, prefix="/api")
    app.include_router(analytics_router)
    app.include_router(identity_router)

    return app


app = create_app()
