from datetime import date

from pydantic import BaseModel


class RevenueSummary(BaseModel):
    start: date
    end: date
    currency: str
    order_count: int
    gross_revenue: float
    average_order_value: float
