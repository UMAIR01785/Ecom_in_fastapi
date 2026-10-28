
from decimal import Decimal
import logging

from fastapi import HTTPException
from langchain_core.tools import tool
from sqlalchemy.orm import Session
from app.schemas.oder import CheckoutRequest

from app.models.cart import Cart
from app.services.cart import (
    add_to_cart as cart_add_to_cart,
    calculate_subtotal,
    get_cart_by_guest_id,
    get_cart_by_user_id,
    remove_from_cart as cart_remove_from_cart,
    update_cart_item as cart_update_item,
)
from app.services.product_search_service import (
    search_products,
    build_shopping_product_response,
)

logger = logging.getLogger(__name__)

MAX_SEARCH_RESULTS = 8
MAX_QUANTITY = 20


def create_customer_product_tools(
    db: Session,
    cart: Cart | None = None,
):
    """Create shopping tools for the current customer's trusted cart."""

    def serialize_cart(current_cart: Cart) -> dict:
        items = []

        for item in current_cart.items:
            product = item.product
            variant = item.variant

            unit_price = (
                Decimal(str(variant.price))
                if variant and variant.price is not None
                else Decimal(str(product.price))
            )

            items.append(
                {
                    "cart_item_id": item.id,
                    "product_id": product.id,
                    "product_name": product.name,
                    "variant_id": variant.id if variant else None,
                    "sku": variant.sku if variant else None,
                    "size": variant.size if variant else None,
                    "color": variant.color if variant else None,
                    "quantity": item.quantity,
                    "unit_price": str(unit_price),
                    "line_total": str(unit_price * item.quantity),
                }
            )

        return {
            "success": True,
            "cart_id": current_cart.id,
            "items": items,
            "subtotal": str(calculate_subtotal(current_cart)),
            "currency": "PKR",
        }

    def refresh_cart() -> Cart | None:
        if cart is None:
            return None

        if cart.user_id is not None:
            return get_cart_by_user_id(db, cart.user_id)

        if cart.guest_id is not None:
            return get_cart_by_guest_id(db, cart.guest_id)

        return None

    @tool
    def search_shoes(
        keyword: str | None = None,
        color: str | None = None,
        category: str | None = None,
        min_price: float | None = None,
        max_price: float | None = None,
        limit: int = 8,
    ) -> dict:
        """Search available shoes by keyword, color, category, and price.
        Prices are in PKR."""

        if not 1 <= limit <= MAX_SEARCH_RESULTS:
            return {"error": "Limit must be between 1 and 8."}

        if min_price is not None and min_price < 0:
            return {"error": "Minimum price cannot be negative."}

        if max_price is not None and max_price < 0:
            return {"error": "Maximum price cannot be negative."}

        if (
            min_price is not None
            and max_price is not None
            and min_price > max_price
        ):
            return {"error": "Minimum price exceeds maximum price."}

        products = search_products(
            db,
            keyword=keyword,
            color=color,
            category=category,
            min_price=(
                Decimal(str(min_price))
                if min_price is not None
                else None
            ),
            max_price=(
                Decimal(str(max_price))
                if max_price is not None
                else None
            ),
            available_only=True,
            limit=limit,
        )

        return {
            "count": len(products),
            "products": [
                build_shopping_product_response(product)
                for product in products
            ],
        }

    @tool
    def get_product_details(product_id: int) -> dict:
        """Retrieve current product details and available variants."""

        if product_id <= 0:
            return {"success": False, "message": "Invalid product ID."}

        try:
            products = search_products(
                db,
                keyword=None,
                color=None,
                category=None,
                min_price=None,
                max_price=None,
                available_only=False,
                limit=MAX_SEARCH_RESULTS,
            )

            product = next(
                (p for p in products if p.id == product_id),
                None,
            )

            if product is None:
                return {
                    "success": False,
                    "message": "Product not found.",
                }

            return {
                "success": True,
                "product": build_shopping_product_response(product),
            }

        except Exception:
            logger.exception("get_product_details failed")
            return {
                "success": False,
                "message": "Could not retrieve product details.",
            }

    @tool
    def add_to_cart(
        product_id: int,
        quantity: int = 1,
        variant_id: int | None = None,
    ) -> dict:
        """Add a product and optional selected variant to the current cart."""

        if cart is None:
            return {"success": False, "message": "Cart is unavailable."}

        if product_id <= 0:
            return {"success": False, "message": "Invalid product ID."}

        if not 1 <= quantity <= MAX_QUANTITY:
            return {
                "success": False,
                "message": "Quantity must be between 1 and 20.",
            }

        if variant_id is not None and variant_id <= 0:
            return {"success": False, "message": "Invalid variant ID."}

        try:
            updated_cart = cart_add_to_cart(
                db=db,
                cart=cart,
                product_id=product_id,
                quantity=quantity,
                variant_id=variant_id,
            )

            return {
                **serialize_cart(updated_cart),
                "message": "Product added to cart successfully.",
            }

        except HTTPException as exc:
            return {"success": False, "message": str(exc.detail)}

        except Exception:
            db.rollback()
            logger.exception("Chatbot add_to_cart failed")
            return {
                "success": False,
                "message": "Could not add the product to the cart.",
            }

    @tool
    def get_cart() -> dict:
        """Retrieve the current cart, selected variants, and subtotal."""

        try:
            current_cart = refresh_cart()

            if current_cart is None:
                return {"success": False, "message": "Cart not found."}

            return serialize_cart(current_cart)

        except Exception:
            logger.exception("Chatbot get_cart failed")
            return {
                "success": False,
                "message": "Could not retrieve the cart.",
            }

    @tool
    def update_cart_item(
        cart_item_id: int,
        quantity: int,
    ) -> dict:
        """Update the quantity of an item belonging to the current cart."""

        if cart is None:
            return {"success": False, "message": "Cart is unavailable."}

        if cart_item_id <= 0:
            return {"success": False, "message": "Invalid cart item ID."}

        if not 1 <= quantity <= MAX_QUANTITY:
            return {
                "success": False,
                "message": "Quantity must be between 1 and 20.",
            }

        try:
            updated_cart = cart_update_item(
                db=db,
                cart=cart,
                cart_item_id=cart_item_id,
                quantity=quantity,
            )

            if updated_cart is None:
                return {"success": False, "message": "Cart not found."}

            return {
                **serialize_cart(updated_cart),
                "message": "Cart quantity updated successfully.",
            }

        except HTTPException as exc:
            return {"success": False, "message": str(exc.detail)}

        except Exception:
            db.rollback()
            logger.exception("Chatbot update_cart_item failed")
            return {
                "success": False,
                "message": "Could not update the cart item.",
            }

    @tool
    def remove_from_cart(cart_item_id: int) -> dict:
        """Remove an item belonging to the current cart."""

        if cart is None:
            return {"success": False, "message": "Cart is unavailable."}

        if cart_item_id <= 0:
            return {"success": False, "message": "Invalid cart item ID."}

        try:
            updated_cart = cart_remove_from_cart(
                db=db,
                cart=cart,
                cart_item_id=cart_item_id,
            )

            if updated_cart is None:
                return {"success": False, "message": "Cart not found."}

            return {
                **serialize_cart(updated_cart),
                "message": "Item removed from cart successfully.",
            }

        except HTTPException as exc:
            return {"success": False, "message": str(exc.detail)}

        except Exception:
            db.rollback()
            logger.exception("Chatbot remove_from_cart failed")
            return {
                "success": False,
                "message": "Could not remove the cart item.",
            }
    @tool
    def prepare_checkout(
        full_name: str,
        phone_number: str,
        address_line1: str,
        city: str,
        country: str,
        payment_method: str,
        address_line2: str | None = None,
        state: str | None = None,
        postal_code: str | None = None,
        landmark: str | None = None,
    ) -> dict:
        """Prepare checkout after collecting the customer's delivery
        address and payment method. This tool does not place an order.
        Ask the customer to review the cart and confirm before checkout."""

        if cart is None:
            return {
                "success": False,
                "message": "Cart is unavailable.",
            }

        current_cart = refresh_cart()

        if current_cart is None or not current_cart.items:
            return {
                "success": False,
                "message": "Your cart is empty. Add shoes before checkout.",
            }

        method = payment_method.strip().upper()

        if method not in {"CARD", "COD"}:
            return {
                "success": False,
                "message": "Choose CARD or COD as the payment method.",
            }

        try:
            checkout_data = CheckoutRequest.model_validate({
                "order_address": {
                    "full_name": full_name,
                    "phone_number": phone_number,
                    "address_line1": address_line1,
                    "address_line2": address_line2,
                    "city": city,
                    "state": state,
                    "postal_code": postal_code,
                    "country": country,
                    "landmark": landmark,
                },
                "payment_method": method,
            })
        except Exception as exc:
            return {
                "success": False,
                "message": f"Invalid checkout details: {exc}",
            }

        cart_summary = serialize_cart(current_cart)

        return {
            "success": True,
            "ready_for_confirmation": True,
            "message": (
                "Checkout details prepared. Show the customer the cart "
                "items, subtotal, delivery address, and payment method. "
                "Ask for explicit confirmation. Do not claim the order "
                "has been placed."
            ),
            "cart": cart_summary,
            "shipping_address": (
                checkout_data.order_address.model_dump()
            ),
            "payment_method": checkout_data.payment_method.value,
        }

    return [
        search_shoes,
        get_product_details,
        add_to_cart,
        get_cart,
        update_cart_item,
        remove_from_cart,
        prepare_checkout,
    ]
