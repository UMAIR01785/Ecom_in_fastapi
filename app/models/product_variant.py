
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class ProductVariant(Base):
    __tablename__ = "product_variants"

    __table_args__ = (
        CheckConstraint(
            "stock >= 0",
            name="ck_product_variants_stock_nonnegative",
        ),
        CheckConstraint(
            "price IS NULL OR price > 0",
            name="ck_product_variants_price_positive",
        ),
    )

    id: Mapped[int] = mapped_column(
        Integer, primary_key=True, index=True
    )

    product_id: Mapped[int] = mapped_column(
        ForeignKey("products.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    sku: Mapped[str] = mapped_column(
        String(100), unique=True, nullable=False, index=True
    )

    size: Mapped[str] = mapped_column(
        String(30), nullable=False
    )

    color: Mapped[str] = mapped_column(
        String(50), nullable=False
    )

    # None means use the parent product's price.
    price: Mapped[Decimal | None] = mapped_column(
        Numeric(10, 2), nullable=True
    )

    stock: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0
    )

    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=datetime.utcnow
    )

    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
    )

    product: Mapped["Product"] = relationship(
        "Product", back_populates="variants"
    )
