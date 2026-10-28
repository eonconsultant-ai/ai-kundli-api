from typing import Annotated

from fastapi import APIRouter, Query, Request

from app.schemas.astro import GeoSearchResponse
from app.services.geo import GeocodingService

router = APIRouter(prefix="/geo", tags=["geocoding"])


@router.get("/search", response_model=GeoSearchResponse, summary="Search Indian places")
async def search_places(
    request: Request,
    q: Annotated[str, Query(min_length=2, max_length=160)],
    limit: Annotated[int, Query(ge=1, le=10)] = 5,
) -> GeoSearchResponse:
    service = GeocodingService(request.app.state.settings)
    places = await service.search(q, limit)
    return GeoSearchResponse(results=places)
