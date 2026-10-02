from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict

from app.models.order import OrderStatus
from app.models.payment import PaymentMethod, PaymentStatus


class AdminPaymentResponse(BaseModel):
    payment_id: int

    order_id: int
    order_status: OrderStatus

    user_id: int

    customer_name: str
    customer_email: str
    customer_phone: str

    amount: Decimal

    payment_method: PaymentMethod
    payment_status: PaymentStatus

    transaction_id: str | None = None
    session_id: str | None = None

    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)