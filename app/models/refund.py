from datetime import datetime
from enum import Enum
from sqlalchemy import Boolean
from sqlalchemy import (
    Column,
    DateTime,
    Enum as SqlEnum,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
)
from sqlalchemy.orm import relationship

from app.database import Base


class RefundStatus(str, Enum):
    REQUESTED = "requested"
    APPROVED = "approved"
    REJECTED = "rejected"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


class Refund(Base):
    __tablename__ = "refunds"

    id = Column(Integer, primary_key=True, index=True)

    order_id = Column(
        Integer,
        ForeignKey("orders.id", ondelete="RESTRICT"),
        nullable=False,
        unique=True,
        index=True,
    )

    requested_by = Column(
        Integer,
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
    )

    reviewed_by = Column(
        Integer,
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )

    amount = Column(Numeric(10, 2), nullable=False)
    reason = Column(String(500), nullable=False)

    status = Column(
        SqlEnum(RefundStatus, name="refundstatus"),
        nullable=False,
        default=RefundStatus.REQUESTED,
    )

    admin_note = Column(Text, nullable=True)

    stripe_refund_id = Column(
        String(255),
        nullable=True,
        unique=True,
    )

    requested_at = Column(
        DateTime,
        nullable=False,
        default=datetime.utcnow,
    )
        # When the returned product was received by the store.
    return_received_at = Column(
        DateTime,
        nullable=True,
    )

    # True = safe to resell; False = damaged/not resellable.
    # None = return has not been inspected yet.
    return_restockable = Column(
        Boolean,
        nullable=True,
    )

    # Records when inventory was restocked, preventing duplication.
    restocked_at = Column(
        DateTime,
        nullable=True,
    )

    reviewed_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)

    order = relationship("Order")
    customer = relationship("User", foreign_keys=[requested_by])
    admin = relationship("User", foreign_keys=[reviewed_by])