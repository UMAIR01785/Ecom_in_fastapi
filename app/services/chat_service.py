
import logging
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.agent import run_admin_agent
from app.models.chat import ChatConversation, ChatMessage

logger = logging.getLogger(__name__)


class ChatAIError(Exception):
    """Raised when the AI cannot generate a response."""


# ============================================================
# SEND ADMIN CHAT MESSAGE
# ============================================================

async def send_chat_message(
    db: AsyncSession,
    conversation_id: int,
    content: str,
) -> ChatMessage:

    # --------------------------------------------------------
    # 1. GET CONVERSATION
    # --------------------------------------------------------

    result = await db.execute(
        select(ChatConversation).where(
            ChatConversation.id == conversation_id
        )
    )

    conversation = result.scalar_one_or_none()

    if conversation is None:
        raise ValueError("Conversation not found")

    content = content.strip()

    if not content:
        raise ValueError("Message cannot be empty")

    now = datetime.now(timezone.utc)

    # --------------------------------------------------------
    # 2. SAVE ADMIN MESSAGE
    # --------------------------------------------------------

    user_message = ChatMessage(
        conversation_id=conversation_id,
        role="user",
        content=content,
    )

    db.add(user_message)

    # Generate title from the first question.
    if conversation.title.strip().lower() == "new chat":
        title = content[:50].strip()

        if len(content) > 50:
            title = title.rstrip() + "..."

        conversation.title = title or "New chat"

    conversation.updated_at = now

    try:
        await db.commit()

    except Exception:
        await db.rollback()

        logger.exception(
            "Failed to save admin chat message"
        )

        raise

    # --------------------------------------------------------
    # 3. LOAD LATEST 12 MESSAGES
    # --------------------------------------------------------

    result = await db.execute(
        select(ChatMessage)
        .where(
            ChatMessage.conversation_id == conversation_id
        )
        .order_by(ChatMessage.id.desc())
        .limit(12)
    )

    recent_messages = result.scalars().all()

    # Reverse to chronological order.
    recent_messages = list(reversed(recent_messages))

    # --------------------------------------------------------
    # 4. GENERATE AI RESPONSE
    # --------------------------------------------------------

    try:
        # run_admin_agent must be async if it uses AsyncSession.
        answer = await run_admin_agent(
            db,
            recent_messages,
        )

        if not answer or not answer.strip():
            raise ValueError("AI returned an empty response")

    except Exception as exc:
        logger.exception(
            "Admin chat AI generation failed"
        )

        raise ChatAIError(
            "The AI assistant is temporarily unavailable."
        ) from exc

    # --------------------------------------------------------
    # 5. SAVE ASSISTANT RESPONSE
    # --------------------------------------------------------

    assistant_message = ChatMessage(
        conversation_id=conversation_id,
        role="assistant",
        content=answer.strip(),
    )

    try:
        db.add(assistant_message)

        conversation.updated_at = datetime.now(timezone.utc)

        await db.commit()
        await db.refresh(assistant_message)

    except Exception:
        await db.rollback()

        logger.exception(
            "Failed to save admin chat response"
        )

        raise

    return assistant_message
