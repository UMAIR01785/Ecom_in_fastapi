
from fastapi import WebSocket, WebSocketDisconnect


class ConnectionManager:
    def __init__(self):
        self.active_connections: dict[int, WebSocket] = {}
        self.admin_connections: set[WebSocket] = set()

    async def connect(self, user_id: int, websocket: WebSocket):
        await websocket.accept()
        self.active_connections[user_id] = websocket

    def disconnect(self, user_id: int, websocket: WebSocket):
        if self.active_connections.get(user_id) is websocket:
            self.active_connections.pop(user_id, None)

    async def send_to_user(self, user_id: int, message: dict):
        websocket = self.active_connections.get(user_id)
        if websocket:
            try:
                await websocket.send_json(message)
            except (WebSocketDisconnect, RuntimeError):
                self.disconnect(user_id, websocket)

    async def connect_admin(self, websocket: WebSocket):
        await websocket.accept()
        self.admin_connections.add(websocket)

    def disconnect_admin(self, websocket: WebSocket):
        self.admin_connections.discard(websocket)

    async def send_to_admin(self, message: dict):
        disconnected = []

        for websocket in list(self.admin_connections):
            try:
                await websocket.send_json(message)
            except (WebSocketDisconnect, RuntimeError):
                disconnected.append(websocket)

        for websocket in disconnected:
            self.disconnect_admin(websocket)


manager = ConnectionManager()
