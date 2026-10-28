from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .astro import KundliRequest

Focus = Literal["life", "career", "relationships", "wellbeing"]
Language = Literal["en", "hi"]


class AiReadingRequest(KundliRequest):
    model_config = ConfigDict(extra="forbid")

    focus: Focus = "life"
    language: Language = "en"
    daily: bool = Field(
        default=False,
        description="Hint that the reading should include one practical step for today.",
    )


class ChatMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=1000)


class AiChatRequest(KundliRequest):
    model_config = ConfigDict(extra="forbid")

    language: Language = "en"
    messages: list[ChatMessage] = Field(min_length=1, max_length=20)

    @model_validator(mode="after")
    def _last_message_is_from_user(self) -> AiChatRequest:
        if self.messages[-1].role != "user":
            raise ValueError("The last chat message must come from the user.")
        return self


class AiLiveSessionRequest(KundliRequest):
    model_config = ConfigDict(extra="forbid")

    language: Language = "en"
    history: list[ChatMessage] = Field(
        default_factory=list,
        max_length=8,
        description="Recent typed or spoken turns, oldest first, for continuity.",
    )


class AiReportRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: Literal["harmful", "inaccurate", "offensive", "other"]
    question: str = Field(default="", max_length=1000)
    reply: str = Field(default="", max_length=2000)
