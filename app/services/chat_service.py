
import logging
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.ai.agent import run_admin_agent
from app.models.chat import ChatConversation, ChatMessage

logger = logging.getLogger(__name__)


class ChatAIError(Exception):
    """Raised when the AI cannot generate a response."""


def send_chat_message(
    db: Session,
    conversation_id: int,
    content: str,
) -> ChatMessage:
    conversation = (
        db.query(ChatConversation)
        .filter(ChatConversation.id == conversation_id)
        .first()
    )

    if conversation is None:
        raise ValueError("Conversation not found")

    content = content.strip()

    if not content:
        raise ValueError("Message cannot be empty")

    now = datetime.now(timezone.utc)

    # 1. Save the admin's question.
    user_message = ChatMessage(
        conversation_id=conversation_id,
        role="user",
        content=content,
    )
    db.add(user_message)

    # 2. Generate the conversation title from the first question.
    if conversation.title.strip().lower() == "new chat":
        title = content[:50].strip()

        if len(content) > 50:
            title = title.rstrip() + "..."

        conversation.title = title or "New chat"

    conversation.updated_at = now

    try:
        db.commit()
    except Exception:
        db.rollback()
        logger.exception("Failed to save admin chat message")
        raise

    # 3. Load the latest messages in chronological order.
    recent_messages = (
        db.query(ChatMessage)
        .filter(
            ChatMessage.conversation_id == conversation_id
        )
        .order_by(ChatMessage.id.desc())
        .limit(12)
        .all()
    )
    recent_messages.reverse()

    # 4. Generate the AI response.
    try:
        answer = run_admin_agent(db, recent_messages)

        if not answer or not answer.strip():
            raise ValueError("AI returned an empty response")

    except Exception as exc:
        logger.exception("Admin chat AI generation failed")
        raise ChatAIError(
            "The AI assistant is temporarily unavailable."
        ) from exc

    # 5. Save the AI response.
    assistant_message = ChatMessage(
        conversation_id=conversation_id,
        role="assistant",
        content=answer.strip(),
    )

    try:
        db.add(assistant_message)
        conversation.updated_at = datetime.now(timezone.utc)

        db.commit()
        db.refresh(assistant_message)

    except Exception:
        db.rollback()
        logger.exception("Failed to save admin chat response")
        raise

    return assistant_message

