from datetime import datetime
from enum import Enum

from sqlalchemy import Column, DateTime, ForeignKey, Integer, Numeric, String
from sqlalchemy import Enum as sqlenum
from sqlalchemy.orm import relationship

from app.database import Base


class PaymentMethod(str, Enum):
    CARD = "card"
    COD = "cod"


class PaymentStatus(str, Enum):
    PENDING = "pending"
    PAID = "paid"
    FAILED = "failed"
    REFUNDED = "refunded"


class Payment(Base):
    __tablename__ = "payments"

    id = Column(Integer, primary_key=True, index=True)

    order_id = Column(
        Integer,
        ForeignKey("orders.id"),
        nullable=False,
        index=True,
    )

    amount = Column(
        Numeric(10, 2),
        nullable=False,
    )

    method = Column(
        sqlenum(PaymentMethod),
        nullable=False,
    )

    status = Column(
        sqlenum(PaymentStatus),
        nullable=False,
        default=PaymentStatus.PENDING,
    )

    session_id = Column(
        String(255),
        nullable=True,
        index=True,
    )

    transaction_id = Column(
        String(255),
        nullable=True,
        unique=True,
    )

    created_at = Column(
        DateTime,
        default=datetime.utcnow,
        nullable=False,
    )

    updated_at = Column(
        DateTime,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
        nullable=False,
    )

    order = relationship(
        "Order",
        back_populates="payment",
    )