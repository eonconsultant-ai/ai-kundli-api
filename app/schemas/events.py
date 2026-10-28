from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class AppEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=2, max_length=40)
    label: str | None = Field(default=None, max_length=40)


class EventBatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    events: list[AppEvent] = Field(min_length=1, max_length=25)
