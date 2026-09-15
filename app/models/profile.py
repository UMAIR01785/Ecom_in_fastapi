from sqlalchemy import ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship
from typing import TYPE_CHECKING
from app.database import Base

if TYPE_CHECKING:
    from app.models.user import User
    
class Profile(Base):
    __tablename__ = "profiles"

    id: Mapped[int] = mapped_column(
        primary_key=True,
        index=True
    )

    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        unique=True,
        nullable=False
    )

    profile_picture: Mapped[str | None] = mapped_column(
        String(500),
        nullable=True
    )

    bio: Mapped[str | None] = mapped_column(
        Text,
        nullable=True
    )

    address: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True
    )

    city: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True
    )

    user: Mapped["User"] = relationship(
        back_populates="profile"
    )   