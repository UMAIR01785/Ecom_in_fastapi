
from datetime import datetime, timezone
import logging

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies.permissions import admin_required
from app.models.chat import ChatConversation, ChatMessage
from app.models.user import User
from app.schemas.chat import (
    ConversationCreate,
    ConversationResponse,
    ChatMessageCreate,
    ChatMessageResponse,
)
from app.services.chat_service import (
    send_chat_message,
    ChatAIError,
)

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/admin/chat",
    tags=["Admin Chat"],
)


def get_admin_conversation(
    db: Session,
    conversation_id: int,
    admin_id: int,
) -> ChatConversation:
    """Fetch a conversation only if it belongs to this admin."""

    conversation = (
        db.query(ChatConversation)
        .filter(
            ChatConversation.id == conversation_id,
            ChatConversation.admin_id == admin_id,
        )
        .first()
    )

    if conversation is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Conversation not found",
        )

    return conversation


@router.post(
    "/conversations",
    response_model=ConversationResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_conversation(
    data: ConversationCreate,
    db: Session = Depends(get_db),
    admin: User = Depends(admin_required),
):
    """Create a new conversation for the logged-in admin."""

    title = data.title.strip()

    if not title:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Conversation title cannot be empty",
        )

    conversation = ChatConversation(
        admin_id=admin.id,
        title=title,
    )

    try:
        db.add(conversation)
        db.commit()
        db.refresh(conversation)
    except Exception:
        db.rollback()
        logger.exception("Failed to create admin chat conversation")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to create conversation",
        )

    return conversation


@router.get(
    "/conversations",
    response_model=list[ConversationResponse],
)
def list_conversations(
    db: Session = Depends(get_db),
    admin: User = Depends(admin_required),
):
    """List only the logged-in admin's conversations."""

    return (
        db.query(ChatConversation)
        .filter(ChatConversation.admin_id == admin.id)
        .order_by(ChatConversation.updated_at.desc())
        .all()
    )


@router.get(
    "/conversations/{conversation_id}/messages",
    response_model=list[ChatMessageResponse],
)
def get_conversation_messages(
    conversation_id: int,
    db: Session = Depends(get_db),
    admin: User = Depends(admin_required),
):
    """Retrieve messages from a conversation owned by this admin."""

    conversation = get_admin_conversation(
        db=db,
        conversation_id=conversation_id,
        admin_id=admin.id,
    )

    return (
        db.query(ChatMessage)
        .filter(
            ChatMessage.conversation_id == conversation.id
        )
        .order_by(
            ChatMessage.created_at.asc(),
            ChatMessage.id.asc(),
        )
        .all()
    )


@router.post(
    "/conversations/{conversation_id}/messages",
    response_model=ChatMessageResponse,
    status_code=status.HTTP_201_CREATED,
)
def save_user_message(
    conversation_id: int,
    data: ChatMessageCreate,
    db: Session = Depends(get_db),
    admin: User = Depends(admin_required),
):
    """
    Save the admin's question, run the AI agent,
    save the AI answer, and return the assistant message.
    """

    conversation = get_admin_conversation(
        db=db,
        conversation_id=conversation_id,
        admin_id=admin.id,
    )

    content = data.content.strip()

    if not content:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Message cannot be empty",
        )

    try:
        assistant_message = send_chat_message(
            db=db,
            conversation_id=conversation.id,
            content=content,
        )

        return assistant_message

    except ChatAIError:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=(
                "The AI assistant could not generate a response. "
                "Your message may already be saved. Please try again."
            ),
        )

    except Exception:
        db.rollback()
        logger.exception("Failed to process admin chat message")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to process chat message",
        )


@router.delete(
    "/conversations/{conversation_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def delete_conversation(
    conversation_id: int,
    db: Session = Depends(get_db),
    admin: User = Depends(admin_required),
):
    """Delete a conversation and its related messages."""

    conversation = get_admin_conversation(
        db=db,
        conversation_id=conversation_id,
        admin_id=admin.id,
    )

    try:
        db.delete(conversation)
        db.commit()
    except Exception:
        db.rollback()
        logger.exception("Failed to delete admin chat conversation")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to delete conversation",
        )

    return None
