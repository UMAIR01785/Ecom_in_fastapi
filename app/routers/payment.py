import stripe

from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    Request,
)

from sqlalchemy.orm import Session, joinedload

from app.config import settings
from app.database import SessionLocal, get_db

from app.models.order import (
    Order,
    OrderStatus,
    OrderItem,
)

from app.models.payment import (
    Payment,
    PaymentStatus,
)

from app.models.product import Product
from app.models.user import User

from app.schemas.payment import (
    PaymentReceiptResponse,
    PaymentReceiptItem,
)

from app.websockets.manager import manager

# IMPORTANT:
# Use the actual location of get_current_user
# from your project.
from app.dependencies.auth import get_current_user


router = APIRouter(
    prefix="/payments",
    tags=["Payments"],
)


# ============================================================
# STRIPE WEBHOOK
# ============================================================

@router.post("/webhook")
async def stripe_webhook(
    request: Request,
):

    # ========================================================
    # 1. Get raw Stripe request
    # ========================================================

    payload = await request.body()

    signature = request.headers.get(
        "stripe-signature"
    )

    if not signature:
        raise HTTPException(
            status_code=400,
            detail="Missing Stripe signature",
        )

    # ========================================================
    # 2. Verify Stripe webhook signature
    # ========================================================

    try:

        event = stripe.Webhook.construct_event(
            payload,
            signature,
            settings.stripe_webhook_secret,
        )

    except ValueError:

        raise HTTPException(
            status_code=400,
            detail="Invalid payload",
        )

    except stripe.error.SignatureVerificationError:

        raise HTTPException(
            status_code=400,
            detail="Invalid Stripe signature",
        )

    # ========================================================
    # 3. Only process checkout.session.completed
    # ========================================================

    if event["type"] != "checkout.session.completed":

        return {
            "received": True,
            "message": "Event ignored",
        }

    # ========================================================
    # 4. Get Stripe Checkout Session
    # ========================================================

    # Stripe returns a StripeObject, not a normal dict.
    # Convert it so .get() works.
    session = event["data"]["object"].to_dict()

    # ========================================================
    # 5. Check Stripe payment status
    # ========================================================

    if session.get("payment_status") != "paid":

        return {
            "received": True,
            "message": "Payment is not paid yet",
        }

    # ========================================================
    # 6. Get metadata
    # ========================================================

    metadata = session.get("metadata") or {}

    payment_id = metadata.get(
        "payment_id"
    )

    order_id = metadata.get(
        "order_id"
    )

    if not payment_id or not order_id:

        raise HTTPException(
            status_code=400,
            detail="Payment metadata missing",
        )

    # ========================================================
    # 7. Create database session
    # ========================================================

    db: Session = SessionLocal()

    try:

        # ====================================================
        # 8. Find payment and lock it
        # ====================================================

        payment = (
            db.query(Payment)
            .filter(
                Payment.id == int(payment_id)
            )
            .with_for_update()
            .first()
        )

        if not payment:

            raise HTTPException(
                status_code=404,
                detail="Payment not found",
            )

        # ====================================================
        # 9. Idempotency check
        # ====================================================

        if payment.status == PaymentStatus.PAID:

            return {
                "received": True,
                "message": "Payment already processed",
            }

        # ====================================================
        # 10. Verify Stripe session
        # ====================================================

        if payment.session_id != session["id"]:

            raise HTTPException(
                status_code=400,
                detail=(
                    "Stripe session does not "
                    "match payment"
                ),
            )

        # ====================================================
        # 11. Verify payment belongs to order
        # ====================================================

        if payment.order_id != int(order_id):

            raise HTTPException(
                status_code=400,
                detail=(
                    "Payment does not belong "
                    "to order"
                ),
            )

        # ====================================================
        # 12. Get and lock order
        #
        # Do NOT use joinedload(Order.items)
        # with with_for_update().
        # ====================================================

        order = (
            db.query(Order)
            .filter(
                Order.id == int(order_id)
            )
            .with_for_update()
            .first()
        )

        if not order:

            raise HTTPException(
                status_code=404,
                detail="Order not found",
            )

        # ====================================================
        # 13. Get order items separately
        # ====================================================

        order_items = (
            db.query(OrderItem)
            .filter(
                OrderItem.order_id == order.id
            )
            .all()
        )

        # ====================================================
        # 14. Verify amount
        # ====================================================

        stripe_amount = session.get(
            "amount_total"
        )

        expected_amount = int(
            payment.amount * 100
        )

        if stripe_amount != expected_amount:

            raise HTTPException(
                status_code=400,
                detail="Payment amount mismatch",
            )

        # ====================================================
        # 15. Update product stock
        # ====================================================

        for order_item in order_items:

            product = (
                db.query(Product)
                .filter(
                    Product.id ==
                    order_item.product_id
                )
                .with_for_update()
                .first()
            )

            if not product:

                raise HTTPException(
                    status_code=400,
                    detail="Product no longer exists",
                )

            if not product.is_active:

                raise HTTPException(
                    status_code=400,
                    detail=(
                        f"Product '{product.name}' "
                        "is no longer available"
                    ),
                )

            if product.stock < order_item.quantity:

                raise HTTPException(
                    status_code=400,
                    detail=(
                        f"Not enough stock for "
                        f"'{product.name}'"
                    ),
                )

            product.stock -= (
                order_item.quantity
            )

        # ====================================================
        # 16. Update payment
        # ====================================================

        payment.status = PaymentStatus.PAID

        payment.transaction_id = (
            session.get("payment_intent")
        )

        # ====================================================
        # 17. Update order
        # ====================================================

        order.status = OrderStatus.CONFIRMED

        # ====================================================
        # 18. Commit everything
        # ====================================================

        db.commit()

        # ====================================================
        # 19. Notify admin
        # ====================================================

        try:

            await manager.send_to_admin({

                "type": "payment_completed",

                "payment_id":
                    payment.id,

                "order_id":
                    order.id,

                "user_id":
                    order.user_id,

                "amount":
                    str(payment.amount),

                "status":
                    payment.status.value,

                "transaction_id":
                    payment.transaction_id,
            })

        except Exception:

            # Payment is already committed.
            # WebSocket failure must not
            # rollback the payment.

            pass

        return {
            "received": True,
            "message": (
                "Payment processed successfully"
            ),
        }

    # ========================================================
    # HTTP exception
    # ========================================================

    except HTTPException:

        db.rollback()

        raise

    # ========================================================
    # Stripe exception
    # ========================================================

    except stripe.error.StripeError as e:

        db.rollback()

        raise HTTPException(
            status_code=400,
            detail=str(e),
        )

    # ========================================================
    # Any other error
    # ========================================================

    except Exception as e:

        db.rollback()

        print(
            "WEBHOOK ERROR:",
            repr(e)
        )

        raise HTTPException(
            status_code=500,
            detail=(
                f"Webhook error: {str(e)}"
            ),
        )

    finally:

        db.close()


# ============================================================
# CUSTOMER PAYMENT RECEIPT
# ============================================================

@router.get(
    "/{payment_id}/receipt",
    response_model=PaymentReceiptResponse,
)
def get_payment_receipt(
    payment_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):

    # ========================================================
    # 1. Find payment
    #
    # Load:
    # Payment
    #   └── Order
    #       ├── User
    #       └── OrderItems
    #           └── Product
    # ========================================================

    payment = (
        db.query(Payment)
        .options(
            joinedload(Payment.order)
            .joinedload(Order.items)
            .joinedload(OrderItem.product),

            joinedload(Payment.order)
            .joinedload(Order.user),
        )
        .filter(
            Payment.id == payment_id
        )
        .first()
    )

    # ========================================================
    # 2. Payment not found
    # ========================================================

    if not payment:

        raise HTTPException(
            status_code=404,
            detail="Payment not found",
        )

    # ========================================================
    # 3. Get order
    # ========================================================

    order = payment.order

    if not order:

        raise HTTPException(
            status_code=404,
            detail="Order not found",
        )

    # ========================================================
    # 4. Security check
    #
    # Customer can only see their own receipt.
    # ========================================================

    if order.user_id != current_user.id:

        raise HTTPException(
            status_code=403,
            detail=(
                "You are not allowed to "
                "view this payment receipt"
            ),
        )

    # ========================================================
    # 5. Build receipt items
    # ========================================================

    receipt_items = []

    for order_item in order.items:

        receipt_items.append(
            PaymentReceiptItem(

                product_id=
                    order_item.product_id,

                product_name=
                    order_item.product.name,

                quantity=
                    order_item.quantity,

                unit_price=
                    order_item.unit_price,

                subtotal=(
                    order_item.unit_price
                    * order_item.quantity
                ),
            )
        )

    # ========================================================
    # 6. Return receipt
    # ========================================================

    return PaymentReceiptResponse(

        payment_id=
            payment.id,

        payment_status=
            payment.status,

        payment_method=
            payment.method,

        amount=
            payment.amount,

        transaction_id=
            payment.transaction_id,

        session_id=
            payment.session_id,

        order_id=
            order.id,

        order_status=
            order.status,

        user_id=
            order.user_id,

        customer_name=(
            f"{order.user.first_name} "
            f"{order.user.last_name}"
        ),

        customer_email=
            order.user.email,

        shipping_address=
            order.shipping_address,

        items=
            receipt_items,

        paid_at=
            payment.paid_at,

        created_at=
            payment.created_at,

        receipt_url=None,
    )