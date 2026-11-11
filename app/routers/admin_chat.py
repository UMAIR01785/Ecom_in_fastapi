
import logging

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

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


async def get_admin_conversation(
    db: AsyncSession,
    conversation_id: int,
    admin_id: int,
) -> ChatConversation:
    """Fetch a conversation only if it belongs to this admin."""

    result = await db.execute(
        select(ChatConversation).where(
            ChatConversation.id == conversation_id,
            ChatConversation.admin_id == admin_id,
        )
    )

    conversation = result.scalar_one_or_none()

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
async def create_conversation(
    data: ConversationCreate,
    db: AsyncSession = Depends(get_db),
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

        await db.commit()
        await db.refresh(conversation)

    except Exception:
        await db.rollback()

        logger.exception(
            "Failed to create admin chat conversation"
        )

        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to create conversation",
        )

    return conversation


@router.get(
    "/conversations",
    response_model=list[ConversationResponse],
)
async def list_conversations(
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(admin_required),
):
    """List only the logged-in admin's conversations."""

    result = await db.execute(
        select(ChatConversation)
        .where(ChatConversation.admin_id == admin.id)
        .order_by(ChatConversation.updated_at.desc())
    )

    return result.scalars().all()


@router.get(
    "/conversations/{conversation_id}/messages",
    response_model=list[ChatMessageResponse],
)
async def get_conversation_messages(
    conversation_id: int,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(admin_required),
):
    """Retrieve messages from a conversation owned by this admin."""

    conversation = await get_admin_conversation(
        db=db,
        conversation_id=conversation_id,
        admin_id=admin.id,
    )

    result = await db.execute(
        select(ChatMessage)
        .where(
            ChatMessage.conversation_id == conversation.id
        )
        .order_by(
            ChatMessage.created_at.asc(),
            ChatMessage.id.asc(),
        )
    )

    return result.scalars().all()


@router.post(
    "/conversations/{conversation_id}/messages",
    response_model=ChatMessageResponse,
    status_code=status.HTTP_201_CREATED,
)
async def save_user_message(
    conversation_id: int,
    data: ChatMessageCreate,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(admin_required),
):
    """
    Save the admin's question, run the AI agent,
    save the AI answer, and return the assistant message.
    """

    conversation = await get_admin_conversation(
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
        assistant_message = await send_chat_message(
            db=db,
            conversation_id=conversation.id,
            content=content,
        )

        return assistant_message

    except ChatAIError:
        await db.rollback()

        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=(
                "The AI assistant could not generate a response. "
                "Your message may already be saved. Please try again."
            ),
        )

    except Exception:
        await db.rollback()

        logger.exception(
            "Failed to process admin chat message"
        )

        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to process chat message",
        )


@router.delete(
    "/conversations/{conversation_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_conversation(
    conversation_id: int,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(admin_required),
):
    """Delete a conversation and its related messages."""

    conversation = await get_admin_conversation(
        db=db,
        conversation_id=conversation_id,
        admin_id=admin.id,
    )

    try:
        await db.delete(conversation)
        await db.commit()

    except Exception:
        await db.rollback()

        logger.exception(
            "Failed to delete admin chat conversation"
        )

        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to delete conversation",
        )

    return None
