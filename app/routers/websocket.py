from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.websockets.manager import manager
from app.websockets.auth import get_websocket_user_id


router = APIRouter()


@router.websocket("/ws/orders")
async def order_websocket(websocket: WebSocket):

    user_id = await get_websocket_user_id(websocket)

    if user_id is None:
        await websocket.close(code=1008)
        return

    await manager.connect(user_id, websocket)

    try:
        while True:
            await websocket.receive_text()

    except WebSocketDisconnect:
        manager.disconnect(user_id)