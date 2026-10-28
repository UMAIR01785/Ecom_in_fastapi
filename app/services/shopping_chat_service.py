
import logging
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.ai.customer_agent import run_customer_agent
from app.models.shopping_chat import (
    ShoppingChatConversation,
    ShoppingChatMessage,
)

logger = logging.getLogger(__name__)


class ShoppingChatAIError(Exception):
    """Raised when the shopping assistant cannot respond."""


def send_shopping_message(
    db: Session,
    *,
    content: str,
    user_id: int | None,
    guest_session_id: str | None,
    conversation_id: int | None = None,
) -> dict:
    content = content.strip()

    if not content:
        raise ValueError("Message cannot be empty")

    if user_id is None and not guest_session_id:
        raise ValueError("A guest session is required")

    # Only retrieve a conversation belonging to this customer/session.
    conversation = None

    if conversation_id is not None:
        query = db.query(ShoppingChatConversation).filter(
            ShoppingChatConversation.id == conversation_id
        )

        if user_id is not None:
            query = query.filter(
                ShoppingChatConversation.user_id == user_id
            )
        else:
            query = query.filter(
                ShoppingChatConversation.user_id.is_(None),
                ShoppingChatConversation.guest_session_id
                == guest_session_id,
            )

        conversation = query.first()

        if conversation is None:
            raise LookupError("Conversation not found")

    now = datetime.now(timezone.utc)

    try:
        if conversation is None:
            conversation = ShoppingChatConversation(
                user_id=user_id,
                guest_session_id=(
                    guest_session_id if user_id is None else None
                ),
                title=content[:157] + ("..." if len(content) > 157 else ""),
                created_at=now,
                updated_at=now,
            )
            db.add(conversation)
            db.flush()

        user_message = ShoppingChatMessage(
            conversation_id=conversation.id,
            role="user",
            content=content,
        )
        db.add(user_message)
        conversation.updated_at = now
        db.commit()
        db.refresh(user_message)

    except Exception:
        db.rollback()
        logger.exception("Failed to save shopping chat message")
        raise

    # Load the latest 12 messages in chronological order.
    history = (
        db.query(ShoppingChatMessage)
        .filter(
            ShoppingChatMessage.conversation_id == conversation.id
        )
        .order_by(ShoppingChatMessage.id.desc())
        .limit(12)
        .all()
    )
    history.reverse()

    # Generate an answer and structured product cards.
    try:
        reply, products = run_customer_agent(
    db=db,
    history=history,
    cart=cart,
)

        if not reply or not reply.strip():
            raise ValueError("The AI returned an empty reply")

    except Exception as exc:
        logger.exception("Shopping chat agent failed")
        raise ShoppingChatAIError(
            "The shopping assistant is temporarily unavailable."
        ) from exc

    assistant_message = ShoppingChatMessage(
        conversation_id=conversation.id,
        role="assistant",
        content=reply.strip(),
    )

    try:
        db.add(assistant_message)
        conversation.updated_at = datetime.now(timezone.utc)
        db.commit()
        db.refresh(assistant_message)
    except Exception:
        db.rollback()
        logger.exception("Failed to save shopping assistant reply")
        raise

    return {
        "conversation_id": conversation.id,
        "reply": reply.strip(),
        "products": products,
        "messages": [user_message, assistant_message],
    }
