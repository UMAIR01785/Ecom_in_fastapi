
import asyncio
from datetime import datetime, timedelta, timezone

import stripe

from app.config import settings
from app.models.order import Order
from app.models.payment import Payment


stripe.api_key = settings.stripe_secret_key

# Stripe requires expiry to be at least 30 minutes
# after session creation, so use a 31-minute safety margin.
CHECKOUT_EXPIRY_SECONDS = 31 * 60


async def create_payment_session(
    order: Order,
    payment: Payment,
):
    # Calculate absolute UTC expiry immediately before
    # creating the Stripe session.
    expiry_utc = (
        datetime.now(timezone.utc)
        + timedelta(seconds=CHECKOUT_EXPIRY_SECONDS)
    )

    # Your SQLAlchemy DateTime column is timezone-naive.
    # Store this UTC value as naive UTC.
    order.reservation_expires_at = expiry_utc.replace(
        tzinfo=None
    )

    session_params = {
        "mode": "payment",
        "expires_at": int(expiry_utc.timestamp()),
        "line_items": [
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
        "metadata": {
            "order_id": str(order.id),
            "payment_id": str(payment.id),
        },
        "payment_intent_data": {
            "metadata": {
                "order_id": str(order.id),
                "payment_id": str(payment.id),
            }
        },
        "success_url": (
            "https://dev-umair.me/"
            "payment/success?session_id={CHECKOUT_SESSION_ID}"
        ),
        "cancel_url": (
            "https://dev-umair.me/"
            "payment/cancel"
        ),
        "idempotency_key": f"checkout-order-{order.id}",
    }

    # Stripe's existing SDK method is synchronous.
    # Run it in a worker thread so it does not block
    # FastAPI's asynchronous event loop.
    session = await asyncio.to_thread(
        stripe.checkout.Session.create,
        **session_params,
    )

    return session
