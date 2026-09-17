from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field


class ProductCreate(BaseModel):
    name: str = Field(
        ...,
        min_length=2,
        max_length=150
    )

    description: str | None = Field(
        default=None,
        max_length=5000
    )

    price: Decimal = Field(
        ...,
        gt=0,
        decimal_places=2
    )

    stock: int = Field(
        default=0,
        ge=0
    )

    category_id: int = Field(
        ...,
        gt=0
    )
    is_active: bool | None = None

class ProductUpdate(BaseModel):
    name: str | None = Field(
        default=None,
        min_length=2,
        max_length=150
    )

    description: str | None = Field(
        default=None,
        max_length=5000
    )

    price: Decimal | None = Field(
        default=None,
        gt=0,
        decimal_places=2
    )

    stock: int | None = Field(
        default=None,
        ge=0
    )

    category_id: int | None = Field(
        default=None,
        gt=0
    )

    is_active: bool | None = None


class ProductResponse(BaseModel):
    id: int
    name: str
    slug: str
    description: str | None
    price: Decimal
    stock: int
    category_id: int
    image: str | None
    is_active: bool
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(
        from_attributes=True
    )