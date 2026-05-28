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


class GameStatus(StrEnum):
    ACTIVE = "active"
    COMING_SOON = "coming_soon"
    HIDDEN = "hidden"


class OrderStatus(StrEnum):
    PENDING = "pending"
    PAID = "paid"
    AWAITING_BOOSTER = "awaiting_booster"
    IN_PROGRESS = "in_progress"
    BOOSTER_COMPLETED = "booster_completed"
    DELIVERED_TO_CLIENT = "delivered_to_client"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    REFUNDED = "refunded"


class PaymentMethod(StrEnum):
    PAYPAL = "paypal"
    USDT_TRC20 = "usdt_trc20"
    CARD_ECOMTRADE24 = "card_ecomtrade24"


class DisplayCurrency(StrEnum):
    USD = "USD"
    EUR = "EUR"


# Allowed status transitions. Empty set = terminal state.
ORDER_STATUS_TRANSITIONS: dict[OrderStatus, frozenset[OrderStatus]] = {
    OrderStatus.PENDING: frozenset({OrderStatus.PAID, OrderStatus.CANCELLED}),
    OrderStatus.PAID: frozenset(
        {OrderStatus.AWAITING_BOOSTER, OrderStatus.CANCELLED, OrderStatus.REFUNDED}
    ),
    OrderStatus.AWAITING_BOOSTER: frozenset(
        {OrderStatus.IN_PROGRESS, OrderStatus.CANCELLED, OrderStatus.REFUNDED}
    ),
    OrderStatus.IN_PROGRESS: frozenset(
        {OrderStatus.BOOSTER_COMPLETED, OrderStatus.CANCELLED, OrderStatus.REFUNDED}
    ),
    OrderStatus.BOOSTER_COMPLETED: frozenset(
        {OrderStatus.DELIVERED_TO_CLIENT, OrderStatus.CANCELLED, OrderStatus.REFUNDED}
    ),
    OrderStatus.DELIVERED_TO_CLIENT: frozenset({OrderStatus.COMPLETED, OrderStatus.REFUNDED}),
    OrderStatus.COMPLETED: frozenset({OrderStatus.REFUNDED}),
    OrderStatus.CANCELLED: frozenset(),
    OrderStatus.REFUNDED: frozenset(),
}
