from __future__ import annotations

from datetime import date, datetime, time
from typing import Literal
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ConfigDict, Field, field_validator

Ayanamsa = Literal["lahiri", "raman", "krishnamurti", "true_citra"]
NodeMode = Literal["true", "mean"]


class GeoPlace(BaseModel):
    name: str
    address: str
    place_id: str
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)
    timezone: str
    utc_offset_seconds: int
    provider: str


class GeoSearchResponse(BaseModel):
    results: list[GeoPlace]


class KundliRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, max_length=120)
    birth_date: date
    birth_time: time
    timezone: str = Field(min_length=1, max_length=64)
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)
    place_name: str | None = Field(default=None, max_length=200)
    altitude_m: float = Field(default=0, ge=-500, le=9000)
    ayanamsa: Ayanamsa = "lahiri"
    node_mode: NodeMode = "true"
    include_pratyantar: bool = True
    transit_at: datetime | None = None

    @field_validator("timezone")
    @classmethod
    def valid_timezone(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except Exception as exc:
            raise ValueError("timezone must be a valid IANA name, e.g. Asia/Kolkata") from exc
        return value

    @field_validator("transit_at")
    @classmethod
    def aware_transit_time(cls, value: datetime | None) -> datetime | None:
        if value is not None and value.tzinfo is None:
            raise ValueError("transit_at must include a UTC offset")
        return value


class EngineMeta(BaseModel):
    name: str
    version: str
    ayanamsas: list[str]
    vargas: dict[str, str]
    node_modes: list[str]
    ephemeris_files_present: bool


class MatchPerson(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, max_length=120)
    birth_date: date
    birth_time: time
    timezone: str = Field(min_length=1, max_length=64)
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)
    place_name: str | None = Field(default=None, max_length=200)

    @field_validator("timezone")
    @classmethod
    def valid_timezone(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except Exception as exc:
            raise ValueError("timezone must be a valid IANA name, e.g. Asia/Kolkata") from exc
        return value


class MatchingRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    bride: MatchPerson
    groom: MatchPerson
    ayanamsa: Ayanamsa = "lahiri"
    node_mode: NodeMode = "true"
    systems: list[Literal["ashtakoot", "mangal_dosha", "lagna"]] = Field(
        default_factory=lambda: ["ashtakoot", "mangal_dosha", "lagna"],
        min_length=1,
        max_length=3,
    )
