from pydantic import BaseModel
from app.models.order import OrderStatus


class OrderStatusUpdate(BaseModel):
    status: OrderStatus