
from jose import JWTError, jwt
from fastapi import WebSocket
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import SECRET_KEY, ALGORITHM
from app.models.user import User


async def get_websocket_user_id(
    websocket: WebSocket,
) -> int | None:
    token = websocket.query_params.get("token")

    if not token:
        return None

    try:
        payload = jwt.decode(
            token,
            SECRET_KEY,
            algorithms=[ALGORITHM],
        )

        if payload.get("type") != "access":
            return None

        user_id = payload.get("sub")

        if user_id is None:
            return None

        return int(user_id)

    except (JWTError, TypeError, ValueError):
        return None


async def get_websocket_user(
    websocket: WebSocket,
    db: AsyncSession,
) -> User | None:

    user_id = await get_websocket_user_id(websocket)

    if user_id is None:
        return None

    result = await db.execute(
        select(User).where(
            User.id == user_id,
            User.is_active.is_(True),
        )
    )

    return result.scalar_one_or_none()
