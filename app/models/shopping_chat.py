
from datetime import datetime, timezone

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class ShoppingChatConversation(Base):
    __tablename__ = "shopping_chat_conversations"

    __table_args__ = (
        CheckConstraint(
            "user_id IS NOT NULL OR guest_session_id IS NOT NULL",
            name="ck_shopping_chat_owner_exists",
        ),
        Index(
            "ix_shopping_chat_user_updated",
            "user_id",
            "updated_at",
        ),
    )

    id: Mapped[int] = mapped_column(
        primary_key=True,
        index=True,
    )

    # NULL means the customer started chatting as a guest.
    user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )

    # A random server-generated session identifier for guests.
    guest_session_id: Mapped[str | None] = mapped_column(
        String(36),
        nullable=True,
        index=True,
    )

    title: Mapped[str] = mapped_column(
        String(160),
        nullable=False,
        default="New shopping chat",
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
    )

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
        onupdate=utc_now,
    )

    messages: Mapped[list["ShoppingChatMessage"]] = relationship(
        back_populates="conversation",
        cascade="all, delete-orphan",
        order_by="ShoppingChatMessage.id",
    )


class ShoppingChatMessage(Base):
    __tablename__ = "shopping_chat_messages"

    __table_args__ = (
        CheckConstraint(
            "role IN ('user', 'assistant')",
            name="ck_shopping_chat_message_role",
        ),
    )

    id: Mapped[int] = mapped_column(
        primary_key=True,
        index=True,
    )

    conversation_id: Mapped[int] = mapped_column(
        ForeignKey(
            "shopping_chat_conversations.id",
            ondelete="CASCADE",
        ),
        nullable=False,
        index=True,
    )

    role: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
    )

    content: Mapped[str] = mapped_column(
        Text,
        nullable=False,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
    )

    conversation: Mapped[ShoppingChatConversation] = relationship(
        back_populates="messages",
    )
