import uuid
from typing import TYPE_CHECKING

from sqlalchemy import ForeignKey, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base

if TYPE_CHECKING:
    from app.models.user import User
    from app.models.product import Product

class Cart(Base):
    __tablename__ = "carts"

    id: Mapped[int] = mapped_column(
        primary_key=True,
        index=True
    )

    user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=True,
        unique=True
    )

    guest_id: Mapped[str | None] = mapped_column(
        nullable=True,
        unique=True,
        index=True
    )

    items: Mapped[list["CartItem"]] = relationship(
        "CartItem",
        back_populates="cart",
        cascade="all, delete-orphan"
    )

    user: Mapped["User | None"] = relationship(
        "User",
        back_populates="cart"
    )


class CartItem(Base):
    __tablename__ = "cart_items"

    id: Mapped[int] = mapped_column(
        primary_key=True,
        index=True
    )

    cart_id: Mapped[int] = mapped_column(
        ForeignKey("carts.id", ondelete="CASCADE"),
        nullable=False
    )

    product_id: Mapped[int] = mapped_column(
        ForeignKey("products.id", ondelete="CASCADE"),
        nullable=False
    )

    quantity: Mapped[int] = mapped_column(
        nullable=False,
        default=1
    )

    cart: Mapped["Cart"] = relationship(
        "Cart",
        back_populates="items"
    )

    product: Mapped["Product"] = relationship(
        "Product"
    )

    __table_args__ = (
        UniqueConstraint(
            "cart_id",
            "product_id",
            name="uq_cart_product"
        ),
    )