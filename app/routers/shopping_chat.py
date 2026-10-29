
import logging
from uuid import uuid4

from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    Request,
    Response,
    status,
)
from sqlalchemy.orm import Session

from app.services.oder_servies import checkout_cart
from app.database import get_db
from app.dependencies.auth import get_optional_current_user
from app.models.user import User
from app.schemas.oder import CheckoutResponse
from app.schemas.shopping_chat import (
    ShoppingChatMessageRequest,
    ShoppingChatResponse,
    ShoppingChatCheckoutRequest,
)
from app.services.shopping_chat_service import (
    ShoppingChatAIError,
    send_shopping_message,
)

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/shopping-chat",
    tags=["Customer Shopping Chat"],
)

GUEST_CHAT_COOKIE = "shopping_chat_session"
GUEST_CART_COOKIE = "guest_cart_id"


@router.post(
    "/messages",
    response_model=ShoppingChatResponse,
)
def send_message(
    data: ShoppingChatMessageRequest,
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
    current_user: User | None = Depends(get_optional_current_user),
):
    guest_session_id = request.cookies.get(GUEST_CHAT_COOKIE)
    guest_cart_id = request.cookies.get(GUEST_CART_COOKIE)

    # Create a separate session ID for guest chat history.
    if current_user is None and not guest_session_id:
        guest_session_id = str(uuid4())

        response.set_cookie(
            key=GUEST_CHAT_COOKIE,
            value=guest_session_id,
            httponly=True,
            samesite="lax",
            secure=request.url.scheme == "https",
            max_age=60 * 60 * 24 * 30,
        )

    # Ensure guest customers have a cart ID.
    if current_user is None and not guest_cart_id:
        guest_cart_id = str(uuid4())

        response.set_cookie(
            key=GUEST_CART_COOKIE,
            value=guest_cart_id,
            httponly=True,
            samesite="lax",
            secure=request.url.scheme == "https",
            max_age=60 * 60 * 24 * 30,
        )

    try:
        return send_shopping_message(
            db=db,
            content=data.message,
            user_id=current_user.id if current_user else None,
            guest_session_id=guest_session_id,
            guest_cart_id=guest_cart_id,
            conversation_id=data.conversation_id,

            # NEW: pass the trusted authenticated user.
            current_user=current_user,

            # Keep false until backend confirmation-state
            # validation is implemented.
            confirmation_authorized=False,
        )

    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc

    except LookupError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Conversation not found",
        ) from exc

    except ShoppingChatAIError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=str(exc),
        ) from exc

    except Exception as exc:
        db.rollback()
        logger.exception("Failed to process shopping chat request")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to process shopping message",
        ) from exc


@router.post(
    "/checkout",
    response_model=CheckoutResponse,
)
async def checkout_from_chat(
    data: ShoppingChatCheckoutRequest,
    db: Session = Depends(get_db),
    current_user: User | None = Depends(get_optional_current_user),
):
    # Checkout is available only to authenticated customers.
    if current_user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Please log in before placing your order.",
        )

    # Require explicit confirmation from the frontend.
    if data.confirmed is not True:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Please confirm your order before checkout.",
        )

    try:
        result = await checkout_cart(
            db=db,
            current_user=current_user,
            checkout_data=data.checkout,
        )
        return result

    except HTTPException:
        raise

    except Exception as exc:
        db.rollback()
        logger.exception("Shopping chat checkout failed")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Checkout failed. Please try again.",
        ) from exc
