from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, model_validator

from app.models.order import OrderStatus


class CheckoutRequest(BaseModel):
    shipping_address: str


class OrderItemResponse(BaseModel):
    id: int
    product_id: int
    quantity: int
    unit_price: Decimal
    product_name: str | None = None
    product_image: str | None = None

    model_config = ConfigDict(from_attributes=True)

    @model_validator(mode="before")
    @classmethod
    def extract_product_fields(cls, data):
        if hasattr(data, "product") and data.product is not None:
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


class OrderResponse(BaseModel):
    id: int
    user_id: int
    status: OrderStatus
    total_amount: Decimal
    shipping_address: str
    created_at: datetime
    items: list[OrderItemResponse]

    model_config = ConfigDict(from_attributes=True)