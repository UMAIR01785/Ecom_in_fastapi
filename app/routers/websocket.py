from fastapi import APIRouter, WebSocket, WebSocketDisconnect , Depends
from sqlalchemy.orm import Session
from app.database import get_db
from app.models.user import UserRole
from app.websockets.manager import manager
from app.websockets.auth import get_websocket_user_id,get_websocket_user


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
        
        
@router.websocket("/ws/admin/orders")
async def admin_order_websocket(
    websocket: WebSocket,
    db: Session = Depends(get_db),
):

    user = await get_websocket_user(
        websocket,
        db
    )

    if user is None:

        await websocket.close(
            code=1008
        )

        return

    if user.role != UserRole.ADMIN:

        await websocket.close(
            code=1008
        )

        return

    await manager.connect_admin(
        websocket
    )

    try:

        while True:

            await websocket.receive_text()

    except WebSocketDisconnect:

        manager.disconnect_admin()