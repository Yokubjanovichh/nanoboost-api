from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_serializer

from app.features.orders.schemas import OrderRead


class PeriodEnum(StrEnum):
    TODAY = "today"
    WEEK = "week"
    MONTH = "month"
    YEAR = "year"


class DashboardOverview(BaseModel):
    period: PeriodEnum
    from_date: datetime
    to_date: datetime
    total_orders: int
    total_revenue_usd: Decimal
    average_order_value_usd: Decimal
    new_clients: int
    by_status: dict[str, int]
    by_payment_method: dict[str, int]

    @field_serializer("total_revenue_usd", "average_order_value_usd")
    def _decimal_to_float(self, value: Decimal) -> float:
        return float(value)


class RevenueChartItem(BaseModel):
    model_config = ConfigDict()

    date: date
    revenue_usd: Decimal
    orders_count: int

    @field_serializer("revenue_usd")
    def _decimal_to_float(self, value: Decimal) -> float:
        return float(value)


class RevenueChartResponse(BaseModel):
    period: PeriodEnum
    items: list[RevenueChartItem]


class TopServiceItem(BaseModel):
    service_id: UUID
    slug: str
    title: str
    orders_count: int
    revenue_usd: Decimal

    @field_serializer("revenue_usd")
    def _decimal_to_float(self, value: Decimal) -> float:
        return float(value)


class TopServicesResponse(BaseModel):
    period: PeriodEnum
    items: list[TopServiceItem] = Field(default_factory=list)


class RecentOrdersResponse(BaseModel):
    items: list[OrderRead]
