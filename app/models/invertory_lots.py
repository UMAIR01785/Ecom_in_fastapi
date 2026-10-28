
from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class InventoryLot(Base):
    __tablename__ = "inventory_lots"

    __table_args__ = (
        CheckConstraint(
            """
            (
                product_id IS NOT NULL
                AND variant_id IS NULL
            )
            OR
            (
                product_id IS NULL
                AND variant_id IS NOT NULL
            )
            """,
            name="ck_inventory_lot_exactly_one_owner",
        ),
        CheckConstraint(
            "quantity_received > 0",
            name="ck_inventory_lot_received_positive",
        ),
        CheckConstraint(
            "quantity_remaining >= 0",
            name="ck_inventory_lot_remaining_nonnegative",
        ),
        CheckConstraint(
            "quantity_remaining <= quantity_received",
            name="ck_inventory_lot_remaining_lte_received",
        ),
        Index("ix_inventory_lots_product_expiry", "product_id", "expires_at"),
        Index("ix_inventory_lots_variant_expiry", "variant_id", "expires_at"),
    )

    id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True,
        index=True,
    )

    lot_number: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
        index=True,
    )

    # Exactly one of product_id or variant_id must be set.
    product_id: Mapped[int | None] = mapped_column(
        ForeignKey("products.id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
    )

    variant_id: Mapped[int | None] = mapped_column(
        ForeignKey("product_variants.id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
    )

    quantity_received: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
    )

    quantity_remaining: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
    )

    # NULL means the lot has no recorded expiry date.
    expires_at: Mapped[datetime | None] = mapped_column(
        DateTime,
        nullable=True,
        index=True,
    )

    received_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        default=datetime.utcnow,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        default=datetime.utcnow,
    )

    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
    )
