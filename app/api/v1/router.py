from fastapi import APIRouter

from . import ai, astro, billing, events, geo

api_router = APIRouter()
api_router.include_router(astro.router)
api_router.include_router(ai.router)
api_router.include_router(billing.router)
api_router.include_router(events.router)
api_router.include_router(geo.router)
