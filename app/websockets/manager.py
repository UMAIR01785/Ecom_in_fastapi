from fastapi import WebSocket


class ConnectionManager:

    def __init__(self):

        # Customer WebSocket connections
        # user_id → WebSocket
        self.active_connections: dict[int, WebSocket] = {}

        # Admin WebSocket connection
        self.admin_connection: WebSocket | None = None

    # -------------------------
    # CUSTOMER
    # -------------------------

    async def connect(
        self,
        user_id: int,
        websocket: WebSocket
    ):

        await websocket.accept()

        self.active_connections[user_id] = websocket

    def disconnect(self, user_id: int):

        self.active_connections.pop(
            user_id,
            None
        )

    async def send_to_user(
        self,
        user_id: int,
        message: dict
    ):

        websocket = self.active_connections.get(
            user_id
        )

        if websocket:

            await websocket.send_json(
                message
            )

    # -------------------------
    # ADMIN
    # -------------------------

    async def connect_admin(
        self,
        websocket: WebSocket
    ):

        await websocket.accept()

        self.admin_connection = websocket

    def disconnect_admin(self):

        self.admin_connection = None

    async def send_to_admin(
        self,
        message: dict
    ):

        if self.admin_connection:

            await self.admin_connection.send_json(
                message
            )


manager = ConnectionManager()