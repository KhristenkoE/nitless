from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.models.order import OrderStatus


class OrderItemIn(BaseModel):
    product_id: int = Field(gt=0)
    quantity: int = Field(ge=1, le=1000)


class OrderCreate(BaseModel):
    items: list[OrderItemIn] = Field(min_length=1, max_length=100)
    coupon_code: str | None = Field(default=None, min_length=3, max_length=32)

    @field_validator("items")
    @classmethod
    def _one_line_per_product(cls, items: list[OrderItemIn]) -> list[OrderItemIn]:
        product_ids = [item.product_id for item in items]
        if len(product_ids) != len(set(product_ids)):
            raise ValueError("each product may appear only once per order; adjust the quantity instead")
        return items


class OrderItemOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    product_id: int
    quantity: int
    unit_price_cents: int
    line_total_cents: int


class OrderOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    customer_id: int
    status: OrderStatus
    currency: str
    subtotal_cents: int
    discount_cents: int
    tax_cents: int
    total_cents: int
    items: list[OrderItemOut]
    created_at: datetime
    paid_at: datetime | None
    shipped_at: datetime | None
