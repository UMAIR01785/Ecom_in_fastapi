
import logging
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.customer_agent import run_customer_agent
from app.models.user import User
from app.models.shopping_chat import (
    ShoppingChatConversation,
    ShoppingChatMessage,
)
from app.services.cart import (
    get_or_create_guest_cart,
    get_or_create_user_cart,
)

logger = logging.getLogger(__name__)


class ShoppingChatAIError(Exception):
    """Raised when the shopping assistant cannot respond."""


async def send_shopping_message(
    db: AsyncSession,
    *,
    content: str,
    user_id: int | None,
    guest_session_id: str | None,
    guest_cart_id: str | None = None,
    conversation_id: int | None = None,
    current_user: User | None = None,
    confirmation_authorized: bool = False,
) -> dict:

    content = content.strip()

    if not content:
        raise ValueError("Message cannot be empty")

    if user_id is None and not guest_session_id:
        raise ValueError("A guest session is required")

    # Ensure the authenticated user and user_id agree.
    if current_user is not None and current_user.id != user_id:
        raise ValueError("Authenticated user does not match user_id")

    if user_id is not None and current_user is None:
        raise ValueError("Authenticated user is required")

    # Guests must never be allowed to place orders through the agent.
    if current_user is None:
        confirmation_authorized = False

    # Retrieve only a conversation owned by this user or guest session.
    conversation = None

    if conversation_id is not None:
        statement = select(ShoppingChatConversation).where(
            ShoppingChatConversation.id == conversation_id
        )

        if user_id is not None:
            statement = statement.where(
                ShoppingChatConversation.user_id == user_id
            )
        else:
            statement = statement.where(
                ShoppingChatConversation.user_id.is_(None),
                ShoppingChatConversation.guest_session_id
                == guest_session_id,
            )

        result = await db.execute(statement)
        conversation = result.scalar_one_or_none()

        if conversation is None:
            raise LookupError("Conversation not found")

    now = datetime.now(timezone.utc)

    # Save the customer's message.
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

            # Generate conversation.id before creating the message.
            await db.flush()

        user_message = ShoppingChatMessage(
            conversation_id=conversation.id,
            role="user",
            content=content,
        )

        db.add(user_message)
        conversation.updated_at = now

        await db.commit()
        await db.refresh(user_message)

    except Exception:
        await db.rollback()
        logger.exception("Failed to save shopping chat message")
        raise

    # Load the latest 12 messages in chronological order.
    history_statement = (
        select(ShoppingChatMessage)
        .where(
            ShoppingChatMessage.conversation_id == conversation.id
        )
        .order_by(ShoppingChatMessage.id.desc())
        .limit(12)
    )

    try:
        history_result = await db.execute(history_statement)
        history = list(history_result.scalars().all())
        history.reverse()

    except Exception:
        logger.exception("Failed to load shopping chat history")
        raise

    # Resolve the correct cart for the current customer.
    try:
        if user_id is not None:
            cart = await get_or_create_user_cart(db, user_id)

        elif guest_cart_id:
            cart = await get_or_create_guest_cart(db, guest_cart_id)

        else:
            cart = None

        # Generate the AI reply and structured product cards.
        reply, products = await run_customer_agent(
            db=db,
            history=history,
            cart=cart,
            current_user=current_user,
            confirmation_authorized=confirmation_authorized,
        )

        if not reply or not reply.strip():
            raise ValueError("The AI returned an empty reply")

    except Exception as exc:
        await db.rollback()

        logger.exception("Shopping chat agent failed")

        raise ShoppingChatAIError(
            "The shopping assistant is temporarily unavailable."
        ) from exc

    # Save the assistant's reply.
    assistant_message = ShoppingChatMessage(
        conversation_id=conversation.id,
        role="assistant",
        content=reply.strip(),
    )

    try:
        db.add(assistant_message)
        conversation.updated_at = datetime.now(timezone.utc)

        await db.commit()
        await db.refresh(assistant_message)

    except Exception:
        await db.rollback()
        logger.exception("Failed to save shopping assistant reply")
        raise

    return {
        "conversation_id": conversation.id,
        "reply": reply.strip(),
        "products": products,
        "messages": [user_message, assistant_message],
    }
