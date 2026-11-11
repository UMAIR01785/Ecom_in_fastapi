
from fastapi import APIRouter, Depends, HTTPException, status

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from app.database import get_db
from app.dependencies.permissions import admin_required
from app.models.order import Order
from app.models.payment import Payment
from app.models.user import User
from app.schemas.admin_payment import AdminPaymentResponse


router = APIRouter(
    prefix="/admin/payments",
    tags=["Admin Payments"],
)


# ============================================================
# HELPER: BUILD PAYMENT RESPONSE
# ============================================================

def build_payment_response(payment: Payment) -> AdminPaymentResponse:

    order = payment.order
    user = order.user

    return AdminPaymentResponse(
        payment_id=payment.id,

        order_id=order.id,
        order_status=order.status,

        user_id=user.id,

        customer_name=(
            f"{user.first_name} "
            f"{user.last_name}"
        ),

        customer_email=user.email,
        customer_phone=user.phone_number,

        amount=payment.amount,

        payment_method=payment.method,
        payment_status=payment.status,

        transaction_id=payment.transaction_id,
        session_id=payment.session_id,

        created_at=payment.created_at,
        updated_at=payment.updated_at,
    )


# ============================================================
# GET ALL PAYMENTS
# ============================================================

@router.get(
    "/",
    response_model=list[AdminPaymentResponse],
)
async def get_all_payments(
    db: AsyncSession = Depends(get_db),
    current_admin: User = Depends(admin_required),
):

    result = await db.execute(
        select(Payment)
        .options(
            joinedload(Payment.order).joinedload(
                Order.user
            )
        )
        .order_by(Payment.created_at.desc())
    )

    payments = result.scalars().all()

    return [
        build_payment_response(payment)
        for payment in payments
    ]


# ============================================================
# GET ONE PAYMENT
# ============================================================

@router.get(
    "/{payment_id}",
    response_model=AdminPaymentResponse,
)
async def get_payment(
    payment_id: int,
    db: AsyncSession = Depends(get_db),
    current_admin: User = Depends(admin_required),
):

    result = await db.execute(
        select(Payment)
        .options(
            joinedload(Payment.order).joinedload(
                Order.user
            )
        )
        .where(Payment.id == payment_id)
    )

    payment = result.scalar_one_or_none()

    if payment is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Payment not found",
        )

    return build_payment_response(payment)
