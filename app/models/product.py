from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    Column,
    Table,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.models.cart import CartItem
from app.database import Base


# =========================================================
# Product <-> Category Association Table
# =========================================================

product_categories = Table(
    "product_categories",
    Base.metadata,

    Column(
        "product_id",
        ForeignKey("products.id", ondelete="CASCADE"),
        primary_key=True,
    ),

    Column(
        "category_id",
        ForeignKey("categories.id", ondelete="CASCADE"),
        primary_key=True,
    ),
)


# =========================================================
# Product Model
# =========================================================

class Product(Base):

    __tablename__ = "products"

    id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True,
        index=True,
    )

    name: Mapped[str] = mapped_column(
        String(150),
        nullable=False,
    )

    slug: Mapped[str] = mapped_column(
        String(180),
        unique=True,
        nullable=False,
        index=True,
    )

    description: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    price: Mapped[float] = mapped_column(
        Numeric(10, 2),
        nullable=False,
    )

    stock: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
    )

    image: Mapped[str | None] = mapped_column(
        String(500),
        nullable=True,
    )

    is_active: Mapped[bool] = mapped_column(
        Boolean,
        default=True,
        nullable=False,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=datetime.utcnow,
        nullable=False,
    )

    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
        nullable=False,
    )

    # =====================================================
    # Many-to-Many Relationship
    # =====================================================

    categories = relationship(
        "Category",
        secondary=product_categories,
        back_populates="products",
    )
    
    
    cart_items: Mapped[list["CartItem"]] = relationship(
    "CartItem",
    back_populates="product"
)

    @property
    def category_slugs(self) -> list[str]:
        return [category.slug for category in self.categories]