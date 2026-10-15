
import stripe

from datetime import datetime, timedelta, timezone

from app.config import settings
from app.models.order import Order
from app.models.payment import Payment

stripe.api_key = settings.stripe_secret_key

# Stripe requires the expiry to be at least 30 minutes
# after session creation, so use a 31-minute safety margin.
CHECKOUT_EXPIRY_SECONDS = 31 * 60


async def create_payment_session(
    order: Order,
    payment: Payment,
):
    # Calculate an absolute UTC timestamp immediately before
    # creating the Stripe session.
    expiry_utc = (
        datetime.now(timezone.utc)
        + timedelta(seconds=CHECKOUT_EXPIRY_SECONDS)
    )

    # Your SQLAlchemy DateTime column is currently timezone-naive.
    # Store this UTC value as naive UTC in the database.
    order.reservation_expires_at = expiry_utc.replace(
        tzinfo=None
    )

    session = stripe.checkout.Session.create(
        mode="payment",
        expires_at=int(expiry_utc.timestamp()),
        line_items=[
            {
                "price_data": {
                    "currency": "pkr",
                    "product_data": {
                        "name": f"Order #{order.id}",
                    },
                    "unit_amount": int(payment.amount * 100),
                },
                "quantity": 1,
            }
        ],
        metadata={
            "order_id": str(order.id),
            "payment_id": str(payment.id),
        },
        payment_intent_data={
            "metadata": {
                "order_id": str(order.id),
                "payment_id": str(payment.id),
            }
        },
        success_url=(
            "http://localhost:5173/payment/success"
            "?session_id={CHECKOUT_SESSION_ID}"
        ),
        cancel_url="http://localhost:5173/payment/cancel",
        idempotency_key=f"checkout-order-{order.id}",
    )

    return session
