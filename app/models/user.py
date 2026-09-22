from sqlalchemy import String,Boolean
from sqlalchemy.orm import Mapped, mapped_column, relationship
from typing import TYPE_CHECKING
from app.database import Base
from enum import Enum

if TYPE_CHECKING:
    from app.models.profile import Profile
    from app.models.cart import Cart
class UserRole(str, Enum):
    CUSTOMER = "customer"
    ADMIN = "admin"

class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)

    first_name: Mapped[str] = mapped_column(
        String(50),
        nullable=False
    )

    last_name: Mapped[str] = mapped_column(
        String(50),
        nullable=False
    )

    email: Mapped[str] = mapped_column(
        String(255),
        unique=True,
        nullable=False
    )

    username: Mapped[str] = mapped_column(
        String(50),
        unique=True,
        nullable=False
    )
    role: Mapped[UserRole] = mapped_column(
            default=UserRole.CUSTOMER
        )
    password_hash: Mapped[str] = mapped_column(
        String(255),
        nullable=False
    )

    phone_number: Mapped[str] = mapped_column(
        String(20),
        unique=True,
        nullable=False
    )

    profile: Mapped["Profile"] = relationship(
        back_populates="user",
        uselist=False,
        cascade="all, delete-orphan"
    )
    
    cart: Mapped["Cart | None"] = relationship(
    "Cart",
    back_populates="user",
    uselist=False
)
    orders = relationship(
    "Order",
    back_populates="user",
    cascade="all, delete-orphan",
)
    
    
    is_active: Mapped[bool] = mapped_column(
    Boolean,
    default=True,
    nullable=False
)