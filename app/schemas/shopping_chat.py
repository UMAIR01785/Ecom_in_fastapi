
from datetime import datetime
from decimal import Decimal
from .oder import CheckoutRequest
from pydantic import BaseModel, ConfigDict, Field


class ShoppingChatMessageRequest(BaseModel):
    """Message sent by the customer to the shopping chatbot."""
    conversation_id: int | None = Field(default=None, gt=0)
    message: str = Field(
        min_length=1,
        max_length=2000,
        description="The customer's shopping question",
    )


class ShoppingChatProductVariantResponse(BaseModel):
    """A selectable size/color variant for a product."""

    id: int
    sku: str
    size: str | None = None
    color: str | None = None
    price: Decimal | None = None
    stock: int

    model_config = ConfigDict(from_attributes=True)


class ShoppingChatProductResponse(BaseModel):
    """Structured product information for frontend product cards."""

    id: int
    name: str
    slug: str
    description: str | None = None
    image: str | None = None
    price: Decimal | None = None
    stock: int
    variants: list[ShoppingChatProductVariantResponse] = Field(
        default_factory=list
    )

    model_config = ConfigDict(from_attributes=True)


class ShoppingChatMessageResponse(BaseModel):
    """A message stored in a shopping conversation."""

    id: int
    role: str
    content: str
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class ShoppingChatResponse(BaseModel):
    """Response returned after processing a customer message."""

    conversation_id: int
    reply: str
    products: list[ShoppingChatProductResponse] = Field(
        default_factory=list
    )
    messages: list[ShoppingChatMessageResponse] = Field(
        default_factory=list
    )

class ShoppingChatCheckoutRequest(BaseModel):
    """Checkout request submitted after customer confirmation."""

    confirmed: bool = Field(
        description="Must be true when the customer confirms the order."
    )
    checkout: CheckoutRequest
