from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class BillingVerifyRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    product_id: str = Field(min_length=1, max_length=120)
    purchase_token: str = Field(min_length=10, max_length=4000)
