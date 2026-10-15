from sqlalchemy.orm import Session
from langchain_core.tools import tool

from app.models.order import Order, OrderStatus


def create_order_tools(db: Session):
    @tool
    def get_order_summary(status: str = "all") -> dict:
        """Count orders and sum their order totals.
        Status can be all, pending, confirmed, processing,
        shipped, delivered, or cancelled.
        """
        query = db.query(Order)

        if status.lower() != "all":
            try:
                selected_status = OrderStatus(status.lower())
            except ValueError:
                return {"error": "Invalid order status"}

            query = query.filter(Order.status == selected_status)

        orders = query.all()

        return {
            "status_filter": status.lower(),
            "order_count": len(orders),
            "total_order_value": str(
                sum((order.total_amount for order in orders), start=0)
            ),
        }

    @tool
    def list_orders(status: str = "all", limit: int = 10) -> dict:
        """List recent orders. Limit must be between 1 and 20."""
        if not 1 <= limit <= 20:
            return {"error": "Limit must be between 1 and 20"}

        query = db.query(Order)

        if status.lower() != "all":
            try:
                selected_status = OrderStatus(status.lower())
            except ValueError:
                return {"error": "Invalid order status"}

            query = query.filter(Order.status == selected_status)

        orders = (
            query.order_by(Order.id.desc())
            .limit(limit)
            .all()
        )

        return {
            "orders": [
                {
                    "id": order.id,
                    "user_id": order.user_id,
                    "status": order.status.value,
                    "total_amount": str(order.total_amount),
                }
                for order in orders
            ]
        }

    @tool
    def get_order_details(order_id: int) -> dict:
        """Retrieve an order by its ID."""
        order = db.query(Order).filter(Order.id == order_id).first()

        if not order:
            return {"error": "Order not found"}

        return {
            "id": order.id,
            "user_id": order.user_id,
            "status": order.status.value,
            "total_amount": str(order.total_amount),
            "created_at": (
                order.created_at.isoformat()
                if order.created_at else None
            ),
        }

    @tool
    def update_order_status(order_id: int, new_status: str) -> dict:
        """Advance an order through permitted statuses.
        Cancellation must use the existing cancellation service.
        """
        allowed_transitions = {
            OrderStatus.PENDING: {OrderStatus.CONFIRMED},
            OrderStatus.CONFIRMED: {OrderStatus.PROCESSING},
            OrderStatus.PROCESSING: {OrderStatus.SHIPPED},
            OrderStatus.SHIPPED: {OrderStatus.DELIVERED},
        }

        order = db.query(Order).filter(Order.id == order_id).first()

        if not order:
            return {"error": "Order not found"}

        try:
            target = OrderStatus(new_status.lower())
        except ValueError:
            return {"error": "Invalid order status"}

        if target not in allowed_transitions.get(order.status, set()):
            return {
                "error": "This order status transition is not permitted",
                "current_status": order.status.value,
                "requested_status": target.value,
            }

        old_status = order.status.value

        try:
            order.status = target
            db.commit()
            db.refresh(order)
        except Exception:
            db.rollback()
            raise

        return {
            "success": True,
            "order_id": order.id,
            "old_status": old_status,
            "new_status": order.status.value,
        }

    return [
        get_order_summary,
        list_orders,
        get_order_details,
        update_order_status,
    ]