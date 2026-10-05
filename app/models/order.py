from datetime import datetime
from enum import Enum

from sqlalchemy import (
    Column,
    Integer,
    Numeric,
    DateTime,
    ForeignKey,
)
from sqlalchemy import Enum as sqlenum
from sqlalchemy.orm import relationship

from app.database import Base

# IMPORTANT:
# Register OrderAddress with SQLAlchemy
from app.models.order_address import OrderAddress


class OrderStatus(str, Enum):
    PENDING = "pending"
    CONFIRMED = "confirmed"
    PROCESSING = "processing"
    SHIPPED = "shipped"
    DELIVERED = "delivered"
    CANCELLED = "cancelled"


class Order(Base):
    __tablename__ = "orders"

    id = Column(
        Integer,
        primary_key=True,
        index=True,
    )

    user_id = Column(
        Integer,
        ForeignKey("users.id"),
        nullable=False,
        index=True,
    )

    total_amount = Column(
        Numeric(10, 2),
        nullable=False,
    )

    status = Column(
        sqlenum(OrderStatus),
        nullable=False,
        default=OrderStatus.PENDING,
    )

    # ============================================================
    # SHIPPING ADDRESS
    # One Order -> One OrderAddress
    # ============================================================

    shipping_address = relationship(
        "OrderAddress",
        back_populates="order",
        uselist=False,
        cascade="all, delete-orphan",
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
    )

    # ============================================================
    # USER
    # ============================================================

    user = relationship(
        "User",
        back_populates="orders",
    )

    # ============================================================
    # ORDER ITEMS
    # ============================================================

    items = relationship(
        "OrderItem",
        back_populates="order",
        cascade="all, delete-orphan",
    )

    # ============================================================
    # PAYMENT
    # ============================================================

    payment = relationship(
        "Payment",
        back_populates="order",
        uselist=False,
        cascade="all, delete-orphan",
    )


class OrderItem(Base):
    __tablename__ = "order_items"

    id = Column(
        Integer,
        primary_key=True,
        index=True,
    )

    order_id = Column(
        Integer,
        ForeignKey("orders.id"),
        nullable=False,
        index=True,
    )

    product_id = Column(
        Integer,
        ForeignKey("products.id"),
        nullable=False,
        index=True,
    )

    quantity = Column(
        Integer,
        nullable=False,
    )

    # Price when the customer purchased the product
    unit_price = Column(
        Numeric(10, 2),
        nullable=False,
    )

    order = relationship(
        "Order",
        back_populates="items",
    )

    product = relationship(
        "Product",
        back_populates="orders",
    )