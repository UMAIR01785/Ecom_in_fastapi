from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field


class CartItemCreate(BaseModel):
    product_id: int
    quantity: int = Field(
        default=1,
        gt=0
    )


class CartItemUpdate(BaseModel):
    quantity: int = Field(
        ...,
        gt=0
    )


class CartProductResponse(BaseModel):
    id: int
    name: str
    slug: str
    price: Decimal
    image: str | None = None

    model_config = ConfigDict(
        from_attributes=True
    )


class CartItemResponse(BaseModel):
    id: int
    product_id: int
    quantity: int

    product: CartProductResponse

    item_total: Decimal

    model_config = ConfigDict(
        from_attributes=True
    )


class CartResponse(BaseModel):
    id: int

    user_id: int | None = None

    guest_id: str | None = None

    items: list[CartItemResponse]

    subtotal: Decimal

    model_config = ConfigDict(
        from_attributes=True
    )