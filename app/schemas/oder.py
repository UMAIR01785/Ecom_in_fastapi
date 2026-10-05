from datetime import datetime
from decimal import Decimal

from pydantic import (
    BaseModel,
    ConfigDict,
    model_validator,
)

from app.models.payment import (
    PaymentMethod,
    PaymentStatus,
)

from app.models.order import OrderStatus


# ============================================================
# ORDER ADDRESS REQUEST
# ============================================================

class OrderAddressRequest(BaseModel):

    full_name: str
    phone_number: str

    address_line1: str
    address_line2: str | None = None

    city: str
    state: str | None = None

    postal_code: str | None = None

    country: str
    landmark: str | None = None


# ============================================================
# CHECKOUT REQUEST
# ============================================================

class CheckoutRequest(BaseModel):

    order_address: OrderAddressRequest

    payment_method: PaymentMethod


# ============================================================
# ORDER ADDRESS RESPONSE
# ============================================================

class OrderAddressResponse(BaseModel):

    id: int

    full_name: str
    phone_number: str

    address_line1: str
    address_line2: str | None = None

    city: str
    state: str | None = None

    postal_code: str | None = None

    country: str
    landmark: str | None = None

    model_config = ConfigDict(
        from_attributes=True,
    )


# ============================================================
# ORDER ITEM RESPONSE
# ============================================================

class OrderItemResponse(BaseModel):

    id: int
    product_id: int
    quantity: int
    unit_price: Decimal

    product_name: str | None = None
    product_image: str | None = None

    model_config = ConfigDict(
        from_attributes=True,
    )

    @model_validator(mode="before")
    @classmethod
    def extract_product_fields(cls, data):

        if (
            hasattr(data, "product")
            and data.product is not None
        ):
            product = data.product

            return {
                "id": data.id,
                "product_id": data.product_id,
                "quantity": data.quantity,
                "unit_price": data.unit_price,
                "product_name": product.name,
                "product_image": product.image,
            }

        return data


# ============================================================
# PAYMENT RESPONSE
# ============================================================

class PaymentResponse(BaseModel):

    id: int
    amount: Decimal

    method: PaymentMethod
    status: PaymentStatus

    transaction_id: str | None = None
    session_id: str | None = None

    created_at: datetime

    model_config = ConfigDict(
        from_attributes=True,
    )


# ============================================================
# ORDER RESPONSE
# ============================================================

class OrderResponse(BaseModel):

    id: int
    user_id: int

    status: OrderStatus
    total_amount: Decimal

    shipping_address: OrderAddressResponse

    created_at: datetime

    items: list[OrderItemResponse]

    payment: PaymentResponse | None = None

    model_config = ConfigDict(
        from_attributes=True,
    )


# ============================================================
# CHECKOUT RESPONSE
# ============================================================

class CheckoutResponse(BaseModel):

    payment_method: PaymentMethod

    order: OrderResponse

    payment_url: str | None = None