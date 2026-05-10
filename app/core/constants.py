from enum import StrEnum


class UserRole(StrEnum):
    SUPERADMIN = "superadmin"
    ADMIN = "admin"
    MANAGER = "manager"
    VIEWER = "viewer"


class TokenType(StrEnum):
    ACCESS = "access"
    REFRESH = "refresh"


class Platform(StrEnum):
    PS = "ps"
    XBOX = "xbox"
    PC = "pc"


class OrderStatus(StrEnum):
    PENDING = "pending"
    PAID = "paid"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    REFUNDED = "refunded"


class PaymentMethod(StrEnum):
    PAYPAL = "paypal"
    USDT_TRC20 = "usdt_trc20"


class DisplayCurrency(StrEnum):
    USD = "USD"
    EUR = "EUR"


# Allowed status transitions. Empty set = terminal state.
ORDER_STATUS_TRANSITIONS: dict[OrderStatus, frozenset[OrderStatus]] = {
    OrderStatus.PENDING: frozenset(
        {OrderStatus.PAID, OrderStatus.CANCELLED}
    ),
    OrderStatus.PAID: frozenset(
        {OrderStatus.IN_PROGRESS, OrderStatus.CANCELLED, OrderStatus.REFUNDED}
    ),
    OrderStatus.IN_PROGRESS: frozenset(
        {OrderStatus.COMPLETED, OrderStatus.CANCELLED, OrderStatus.REFUNDED}
    ),
    OrderStatus.COMPLETED: frozenset({OrderStatus.REFUNDED}),
    OrderStatus.CANCELLED: frozenset(),
    OrderStatus.REFUNDED: frozenset(),
}
