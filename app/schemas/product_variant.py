
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field


class ProductVariantCreate(BaseModel):
    sku: str = Field(min_length=1, max_length=100)
    size: str = Field(min_length=1, max_length=30)
    color: str = Field(min_length=1, max_length=50)

    price: Decimal | None = Field(
        default=None,
        gt=0,
        decimal_places=2,
    )

    stock: int = Field(default=0, ge=0)
    is_active: bool = True


class ProductVariantUpdate(BaseModel):
    sku: str | None = Field(
        default=None,
        min_length=1,
        max_length=100,
    )
    size: str | None = Field(
        default=None,
        min_length=1,
        max_length=30,
    )
    color: str | None = Field(
        default=None,
        min_length=1,
        max_length=50,
    )
    price: Decimal | None = Field(
        default=None,
        gt=0,
        decimal_places=2,
    )
    stock: int | None = Field(default=None, ge=0)
    is_active: bool | None = None


class ProductVariantResponse(BaseModel):
    id: int
    product_id: int
    sku: str
    size: str
    color: str
    price: Decimal | None
    stock: int
    is_active: bool
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)
