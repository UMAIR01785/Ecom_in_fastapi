from fastapi import WebSocket, WebSocketDisconnect


class ConnectionManager:
    def __init__(self):
        self.active_connections: dict[int, set[WebSocket]] = {}
        self.admin_connections: set[WebSocket] = set()
        self.catalog_connections: set[WebSocket] = set()

    # Customer order/payment socket
    async def connect(self, user_id: int, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.setdefault(user_id, set()).add(websocket)

    def disconnect(self, user_id: int, websocket: WebSocket):
        connections = self.active_connections.get(user_id)

        if connections:
            connections.discard(websocket)

            if not connections:
                self.active_connections.pop(user_id, None)

    async def send_to_user(self, user_id: int, message: dict):
        disconnected = []

        for websocket in list(self.active_connections.get(user_id, set())):
            try:
                await websocket.send_json(message)
            except (WebSocketDisconnect, RuntimeError, OSError):
                disconnected.append(websocket)

        for websocket in disconnected:
            self.disconnect(user_id, websocket)

    # Admin dashboard socket
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
            except (WebSocketDisconnect, RuntimeError, OSError):
                disconnected.append(websocket)

        for websocket in disconnected:
            self.disconnect_admin(websocket)

    # Public storefront catalog socket
    async def connect_catalog(self, websocket: WebSocket):
        await websocket.accept()
        self.catalog_connections.add(websocket)

    def disconnect_catalog(self, websocket: WebSocket):
        self.catalog_connections.discard(websocket)

    async def broadcast_to_catalog(self, message: dict):
        disconnected = []

        for websocket in list(self.catalog_connections):
            try:
                await websocket.send_json(message)
            except (WebSocketDisconnect, RuntimeError, OSError):
                disconnected.append(websocket)

        for websocket in disconnected:
            self.disconnect_catalog(websocket)


manager = ConnectionManager()