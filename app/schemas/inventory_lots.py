from datetime import datetime
from pydantic import BaseModel, ConfigDict, Field, model_validator


class InventoryLotCreate(BaseModel):
    lot_number: str = Field(min_length=1, max_length=100)
    product_id: int | None = Field(default=None, gt=0)
    variant_id: int | None = Field(default=None, gt=0)
    quantity: int = Field(gt=0)
    expires_at: datetime | None = None

    @model_validator(mode="after")
    def validate_owner(self):
        if (self.product_id is None) == (self.variant_id is None):
            raise ValueError(
                "Provide exactly one of product_id or variant_id"
            )

        self.lot_number = self.lot_number.strip()
        if not self.lot_number:
            raise ValueError("lot_number cannot be empty")

        return self


class InventoryLotResponse(BaseModel):
    id: int
    lot_number: str
    product_id: int | None
    variant_id: int | None
    quantity_received: int
    quantity_remaining: int
    expires_at: datetime | None
    received_at: datetime

    model_config = ConfigDict(from_attributes=True)