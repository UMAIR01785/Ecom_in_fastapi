from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field

from app.models.refund import RefundStatus


class RefundRequestCreate(BaseModel):
    reason: str = Field(min_length=5, max_length=500)


class RefundReviewRequest(BaseModel):
    decision: str = Field(pattern="^(approve|reject)$")
    admin_note: str | None = Field(default=None, max_length=2000)


class RefundResponse(BaseModel):
    id: int
    order_id: int
    requested_by: int
    reviewed_by: int | None
    amount: Decimal
    reason: str
    status: RefundStatus
    admin_note: str | None
    stripe_refund_id: str | None
    requested_at: datetime
    reviewed_at: datetime | None
    completed_at: datetime | None

    model_config = ConfigDict(from_attributes=True)