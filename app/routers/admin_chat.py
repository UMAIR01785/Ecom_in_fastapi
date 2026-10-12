
from datetime import datetime, timezone

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
    conversation = ChatConversation(
        admin_id=admin.id,
        title=data.title.strip(),
    )

    db.add(conversation)
    db.commit()
    db.refresh(conversation)

    return conversation


@router.get(
    "/conversations",
    response_model=list[ConversationResponse],
)
def list_conversations(
    db: Session = Depends(get_db),
    admin: User = Depends(admin_required),
):
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

    message = ChatMessage(
        conversation_id=conversation.id,
        role="user",
        content=content,
    )

    conversation.updated_at = datetime.now(timezone.utc)

    try:
        db.add(message)
        db.commit()
        db.refresh(message)
    except Exception:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to save message",
        )

    return message


@router.delete(
    "/conversations/{conversation_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def delete_conversation(
    conversation_id: int,
    db: Session = Depends(get_db),
    admin: User = Depends(admin_required),
):
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
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to delete conversation",
        )

    return None
