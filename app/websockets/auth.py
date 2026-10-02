from jose import JWTError, jwt
from fastapi import WebSocket
from sqlalchemy.orm import Session

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

        user_id = payload.get("sub")

        if user_id is None:
            return None

        return int(user_id)

    except (JWTError, ValueError):

        return None


async def get_websocket_user(
    websocket: WebSocket,
    db: Session,
) -> User | None:

    user_id = await get_websocket_user_id(
        websocket
    )

    if user_id is None:
        return None

    user = (
        db.query(User)
        .filter(User.id == user_id)
        .first()
    )

    return user