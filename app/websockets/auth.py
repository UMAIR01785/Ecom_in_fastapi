from jose import JWTError, jwt
from fastapi import WebSocket

from app.core.security import SECRET_KEY, ALGORITHM


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