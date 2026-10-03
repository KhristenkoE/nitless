from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.models.payment import PaymentStatus


class PaymentCreate(BaseModel):
    order_id: int = Field(gt=0)
    payment_token: str = Field(min_length=1, max_length=255)


class PaymentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    order_id: int
    status: PaymentStatus
    amount_cents: int
    refunded_cents: int
    currency: str
    captured_at: datetime | None
    created_at: datetime


class RefundCreate(BaseModel):
    reason: str = Field(min_length=1, max_length=500)
    amount_cents: int | None = Field(default=None, gt=0, description="defaults to the remaining refundable amount")


class RefundOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    payment_id: int
    amount_cents: int
    reason: str
    created_at: datetime
