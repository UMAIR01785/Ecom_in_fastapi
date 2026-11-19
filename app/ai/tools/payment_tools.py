
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from langchain_core.tools import tool

from app.models.payment import Payment, PaymentStatus


def create_payment_tools(db: AsyncSession):

    @tool
    async def get_payment_summary() -> dict:
        """Count payments and sum amounts grouped by payment status."""

        query = (
            select(
                Payment.status,
                func.count(Payment.id),
                func.coalesce(func.sum(Payment.amount), 0),
            )
            .group_by(Payment.status)
        )

        result = await db.execute(query)
        rows = result.all()

        return {
            "payments": [
                {
                    "status": payment_status.value,
                    "count": count,
                    "amount": str(amount),
                }
                for payment_status, count, amount in rows
            ]
        }

    @tool
    async def get_payment_details(payment_id: int) -> dict:
        """Retrieve payment details by payment ID."""

        if payment_id <= 0:
            return {"error": "Invalid payment ID"}

        result = await db.execute(
            select(Payment).where(Payment.id == payment_id)
        )

        payment = result.scalar_one_or_none()

        if not payment:
            return {"error": "Payment not found"}

        return {
            "payment_id": payment.id,
            "order_id": payment.order_id,
            "amount": str(payment.amount),
            "method": payment.method.value,
            "status": payment.status.value,
            "transaction_id": payment.transaction_id,
            "session_id": payment.session_id,
        }

    @tool
    async def get_paid_sales_summary() -> dict:
        """Sum payment records marked as paid."""

        query = (
            select(
                func.count(Payment.id),
                func.coalesce(func.sum(Payment.amount), 0),
            )
            .where(Payment.status == PaymentStatus.PAID)
        )

        result = await db.execute(query)
        count, total = result.one()

        return {
            "paid_payment_count": count,
            "paid_payment_amount": str(total),
            "basis": "Payment records marked paid",
        }

    return [
        get_payment_summary,
        get_payment_details,
        get_paid_sales_summary,
    ]
