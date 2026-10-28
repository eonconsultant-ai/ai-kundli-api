"""Place search and IANA timezone resolution."""

from __future__ import annotations

from datetime import datetime
from functools import lru_cache
from zoneinfo import ZoneInfo

import httpx
from timezonefinder import TimezoneFinder

from app.core.config import Settings
from app.schemas.astro import GeoPlace


class GeoLookupError(RuntimeError):
    pass


@lru_cache
def _timezone_finder() -> TimezoneFinder:
    return TimezoneFinder()


def _timezone_for(latitude: float, longitude: float) -> str:
    tz_name = _timezone_finder().timezone_at(lat=latitude, lng=longitude)
    if not tz_name:
        return "UTC"
    try:
        ZoneInfo(tz_name)
    except Exception:
        return "UTC"
    return tz_name


def _utc_offset(tz_name: str) -> int:
    offset = datetime.now(ZoneInfo(tz_name)).utcoffset()
    return int(offset.total_seconds()) if offset else 0


def _place(
    *,
    name: str,
    address: str,
    place_id: str,
    latitude: float,
    longitude: float,
    provider: str,
) -> GeoPlace:
    tz_name = _timezone_for(latitude, longitude)
    return GeoPlace(
        name=name,
        address=address,
        place_id=place_id,
        latitude=latitude,
        longitude=longitude,
        timezone=tz_name,
        utc_offset_seconds=_utc_offset(tz_name),
        provider=provider,
    )


class GeocodingService:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    @property
    def provider(self) -> str:
        if self._settings.geocoding_provider == "auto":
            return "google" if self._settings.google_maps_api_key else "photon"
        return self._settings.geocoding_provider

    async def search(self, query: str, limit: int = 5) -> list[GeoPlace]:
        if self.provider == "google":
            return await self._search_google(query, limit)
        if self.provider == "nominatim":
            return await self._search_nominatim(query, limit)
        return await self._search_photon(query, limit)

    async def _search_google(self, query: str, limit: int) -> list[GeoPlace]:
        api_key = self._settings.google_maps_api_key
        if not api_key:
            raise GeoLookupError("GOOGLE_MAPS_API_KEY is not configured.")

        headers = {
            "Content-Type": "application/json",
            "X-Goog-Api-Key": api_key,
            "X-Goog-FieldMask": ("places.id,places.displayName,places.formattedAddress,places.location,places.types"),
        }
        body = {
            "textQuery": query,
            "languageCode": "en",
            "regionCode": "in",
            "maxResultCount": limit,
        }
        try:
            async with httpx.AsyncClient(timeout=self._settings.http_timeout_seconds) as client:
                response = await client.post(
                    "https://places.googleapis.com/v1/places:searchText",
                    headers=headers,
                    json=body,
                )
                response.raise_for_status()
                payload = response.json()
        except httpx.HTTPError as exc:
            raise GeoLookupError(f"Google Places request failed: {exc}") from exc

        results: list[GeoPlace] = []
        for item in payload.get("places", []):
            location = item.get("location") or {}
            if "latitude" not in location or "longitude" not in location:
                continue
            results.append(
                _place(
                    name=(item.get("displayName") or {}).get("text", query),
                    address=item.get("formattedAddress", ""),
                    place_id=item.get("id", ""),
                    latitude=float(location["latitude"]),
                    longitude=float(location["longitude"]),
                    provider="google",
                )
            )
        return results

    async def _search_nominatim(self, query: str, limit: int) -> list[GeoPlace]:
        headers = {"User-Agent": self._settings.geocoding_user_agent}
        params = {
            "q": query,
            "format": "jsonv2",
            "limit": limit,
            "countrycodes": "in",
            "addressdetails": 0,
        }
        try:
            async with httpx.AsyncClient(timeout=self._settings.http_timeout_seconds) as client:
                response = await client.get(
                    f"{self._settings.nominatim_base_url}/search",
                    headers=headers,
                    params=params,
                )
                response.raise_for_status()
                rows = response.json()
        except httpx.HTTPError as exc:
            raise GeoLookupError(f"Nominatim request failed: {exc}") from exc

        results: list[GeoPlace] = []
        for item in rows:
            display_name = item.get("display_name", "")
            results.append(
                _place(
                    name=display_name.split(",")[0] or query,
                    address=display_name,
                    place_id=str(item.get("place_id", "")),
                    latitude=float(item["lat"]),
                    longitude=float(item["lon"]),
                    provider="nominatim",
                )
            )
        return results

    async def _search_photon(self, query: str, limit: int) -> list[GeoPlace]:
        headers = {"User-Agent": self._settings.geocoding_user_agent}
        params = {
            "q": query,
            "limit": min(limit * 4, 20),
            "lang": "en",
        }
        try:
            async with httpx.AsyncClient(timeout=self._settings.http_timeout_seconds) as client:
                response = await client.get(
                    f"{self._settings.photon_base_url}/api/",
                    headers=headers,
                    params=params,
                )
                response.raise_for_status()
                payload = response.json()
        except httpx.HTTPError as exc:
            raise GeoLookupError(f"Photon request failed: {exc}") from exc

        results: list[GeoPlace] = []
        for item in payload.get("features", []):
            properties = item.get("properties") or {}
            if properties.get("countrycode", "").upper() != "IN":
                continue
            coordinates = (item.get("geometry") or {}).get("coordinates") or []
            if len(coordinates) < 2:
                continue
            address_parts: list[str] = []
            for key in ("name", "city", "state", "country"):
                value = properties.get(key)
                if value and value not in address_parts:
                    address_parts.append(value)
            results.append(
                _place(
                    name=(
                        properties.get("name")
                        or properties.get("city")
                        or properties.get("state")
                        or query
                    ),
                    address=", ".join(address_parts) or query,
                    place_id=(
                        f"{properties.get('osm_type', '')}"
                        f"{properties.get('osm_id', '')}"
                    ),
                    latitude=float(coordinates[1]),
                    longitude=float(coordinates[0]),
                    provider="photon",
                )
            )
            if len(results) >= limit:
                break
        return results
