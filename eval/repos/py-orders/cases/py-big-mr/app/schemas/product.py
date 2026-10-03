# Copyright (c) 2026 Acme Commerce GmbH
# SPDX-License-Identifier: Apache-2.0

from pydantic import BaseModel, ConfigDict, Field


class ProductCreate(BaseModel):
    sku: str = Field(pattern=r"^[A-Z0-9][A-Z0-9-]{2,63}$")
    name: str = Field(min_length=1, max_length=200)
    unit_price_cents: int = Field(gt=0)
    currency: str = Field(default="USD", pattern=r"^[A-Z]{3}$")
    stock_quantity: int = Field(default=0, ge=0)


class ProductOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    sku: str
    name: str
    unit_price_cents: int
    currency: str
    active: bool
    stock_quantity: int
