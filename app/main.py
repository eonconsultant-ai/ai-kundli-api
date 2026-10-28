import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.v1.router import api_router
from app.core.config import get_settings
from app.core.ratelimit import RateLimitMiddleware
from app.services.ai import store
from app.services.astro.ephemeris import configure_ephemeris
from app.services.astro.time import AstroInputError
from app.services.geo import GeoLookupError

logger = logging.getLogger("jyotish")


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = app.state.settings
    configure_ephemeris(settings.ephe_path)
    store.get(settings).prune()
    if not any(settings.ephe_path.glob("*.se1")):
        logger.warning(
            "No Swiss Ephemeris .se1 files found in %s; falling back to Moshier. "
            "Run scripts/fetch_ephemeris.py for full precision.",
            settings.ephe_path.resolve(),
        )
    yield


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title=settings.app_name,
        version="0.1.0",
        lifespan=lifespan,
        docs_url="/docs" if settings.environment != "production" else None,
        redoc_url=None,
    )
    app.state.settings = settings

    # Added before CORS so CORS stays outermost and its headers, as well as
    # preflight handling, still apply to the 429s this middleware returns.
    app.add_middleware(
        RateLimitMiddleware,
        prefix=settings.api_v1_prefix,
        enabled=settings.rate_limit_enabled,
    )

    cors_origins = settings.cors_origin_list
    app.add_middleware(
        CORSMiddleware,
        allow_origins=cors_origins,
        allow_credentials=cors_origins != ["*"],
        allow_methods=["GET", "POST", "DELETE"],
        allow_headers=["*"],
    )

    app.include_router(api_router, prefix=settings.api_v1_prefix)

    @app.exception_handler(AstroInputError)
    async def astro_input_error(_: Request, exc: AstroInputError) -> JSONResponse:
        return JSONResponse(status_code=422, content={"detail": str(exc)})

    @app.exception_handler(GeoLookupError)
    async def geo_error(_: Request, exc: GeoLookupError) -> JSONResponse:
        return JSONResponse(status_code=502, content={"detail": str(exc)})

    # Cloud Run's front end answers /healthz itself, so the probe lives at /health.
    @app.get("/health", tags=["ops"])
    def health() -> dict:
        return {"status": "ok", "service": settings.app_name, "version": "0.1.0"}

    @app.get("/readyz", tags=["ops"])
    def readyz(request: Request) -> dict:
        ephe_path = request.app.state.settings.ephe_path
        return {
            "status": "ready",
            "ephemeris_files_present": ephe_path.exists() and any(ephe_path.glob("*.se1")),
        }

    return app


app = create_app()
