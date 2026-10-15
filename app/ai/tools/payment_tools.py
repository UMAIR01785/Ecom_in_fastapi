from sqlalchemy import func
from sqlalchemy.orm import Session
from langchain_core.tools import tool

from app.models.payment import Payment, PaymentStatus


def create_payment_tools(db: Session):
    @tool
    def get_payment_summary() -> dict:
        """Count payments and sum amounts grouped by payment status."""
        rows = (
            db.query(
                Payment.status,
                func.count(Payment.id),
                func.coalesce(func.sum(Payment.amount), 0),
            )
            .group_by(Payment.status)
            .all()
        )

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
    def get_payment_details(payment_id: int) -> dict:
        """Retrieve payment details by payment ID."""
        payment = (
            db.query(Payment)
            .filter(Payment.id == payment_id)
            .first()
        )

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
    def get_paid_sales_summary() -> dict:
        """Sum payment records marked as paid."""
        count, total = (
            db.query(
                func.count(Payment.id),
                func.coalesce(func.sum(Payment.amount), 0),
            )
            .filter(Payment.status == PaymentStatus.PAID)
            .one()
        )

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