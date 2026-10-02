from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict

from app.models.order import OrderStatus
from app.models.payment import PaymentMethod, PaymentStatus


class PaymentReceiptItem(BaseModel):
    product_id: int
    product_name: str
    quantity: int
    unit_price: Decimal
    subtotal: Decimal


class PaymentReceiptResponse(BaseModel):
    payment_id: int

    payment_status: PaymentStatus
    payment_method: PaymentMethod

    amount: Decimal

    transaction_id: str | None = None
    session_id: str | None = None

    order_id: int
    order_status: OrderStatus

    user_id: int

    customer_name: str
    customer_email: str

    shipping_address: str

    items: list[PaymentReceiptItem]

    paid_at: datetime | None = None
    created_at: datetime

    receipt_url: str | None = None

    model_config = ConfigDict(from_attributes=True)