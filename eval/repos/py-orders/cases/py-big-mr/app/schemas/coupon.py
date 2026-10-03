# Copyright (c) 2026 Acme Commerce GmbH
# SPDX-License-Identifier: Apache-2.0

from datetime import datetime

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field


class CouponCreate(BaseModel):
    code: str = Field(pattern=r"^[A-Za-z0-9_-]{3,32}$")
    percent_off: int = Field(ge=1, le=100, description="whole percent, e.g. 15 for 15% off")
    expires_at: AwareDatetime | None = None


class CouponOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    code: str
    percent_off: int
    active: bool
    expires_at: datetime | None
    created_at: datetime
