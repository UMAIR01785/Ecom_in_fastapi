from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session, joinedload

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
# GET ALL PAYMENTS
# ============================================================

@router.get(
    "/",
    response_model=list[AdminPaymentResponse],
)
def get_all_payments(
    db: Session = Depends(get_db),
    current_admin: User = Depends(admin_required),
):

    payments = (
        db.query(Payment)
        .options(
            joinedload(Payment.order)
            .joinedload(Order.user)
        )
        .order_by(
            Payment.created_at.desc()
        )
        .all()
    )

    response = []

    for payment in payments:

        order = payment.order
        user = order.user

        response.append(
            AdminPaymentResponse(
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
        )

    return response


# ============================================================
# GET ONE PAYMENT
# ============================================================

@router.get(
    "/{payment_id}",
    response_model=AdminPaymentResponse,
)
def get_payment(
    payment_id: int,
    db: Session = Depends(get_db),
    current_admin: User = Depends(admin_required),
):

    payment = (
        db.query(Payment)
        .options(
            joinedload(Payment.order)
            .joinedload(Order.user)
        )
        .filter(
            Payment.id == payment_id
        )
        .first()
    )

    if not payment:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Payment not found",
        )

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