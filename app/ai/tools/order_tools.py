
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from langchain_core.tools import tool

from app.models.order import Order, OrderStatus


def create_order_tools(db: AsyncSession):

    @tool
    async def get_order_summary(status: str = "all") -> dict:
        """Count orders and sum their order totals.
        Status can be all, pending, confirmed, processing,
        shipped, delivered, or cancelled.
        """

        query = select(
            func.count(Order.id),
            func.coalesce(func.sum(Order.total_amount), 0),
        )

        if status.lower() != "all":
            try:
                selected_status = OrderStatus(status.lower())
            except ValueError:
                return {"error": "Invalid order status"}

            query = query.where(Order.status == selected_status)

        result = await db.execute(query)
        order_count, total_order_value = result.one()

        return {
            "status_filter": status.lower(),
            "order_count": order_count,
            "total_order_value": str(total_order_value),
        }

    @tool
    async def list_orders(
        status: str = "all",
        limit: int = 10,
    ) -> dict:
        """List recent orders. Limit must be between 1 and 20."""

        if not 1 <= limit <= 20:
            return {"error": "Limit must be between 1 and 20"}

        query = select(Order)

        if status.lower() != "all":
            try:
                selected_status = OrderStatus(status.lower())
            except ValueError:
                return {"error": "Invalid order status"}

            query = query.where(Order.status == selected_status)

        query = query.order_by(Order.id.desc()).limit(limit)

        result = await db.execute(query)
        orders = result.scalars().all()

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
    async def get_order_details(order_id: int) -> dict:
        """Retrieve an order by its ID."""

        if order_id <= 0:
            return {"error": "Invalid order ID"}

        result = await db.execute(
            select(Order).where(Order.id == order_id)
        )

        order = result.scalar_one_or_none()

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
    async def update_order_status(
        order_id: int,
        new_status: str,
    ) -> dict:
        """Advance an order through permitted statuses.
        Cancellation must use the existing cancellation service.
        """

        allowed_transitions = {
            OrderStatus.PENDING: {OrderStatus.CONFIRMED},
            OrderStatus.CONFIRMED: {OrderStatus.PROCESSING},
            OrderStatus.PROCESSING: {OrderStatus.SHIPPED},
            OrderStatus.SHIPPED: {OrderStatus.DELIVERED},
        }

        if order_id <= 0:
            return {"error": "Invalid order ID"}

        result = await db.execute(
            select(Order)
            .where(Order.id == order_id)
            .with_for_update()
        )

        order = result.scalar_one_or_none()

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

            await db.commit()
            await db.refresh(order)

        except Exception:
            await db.rollback()
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
