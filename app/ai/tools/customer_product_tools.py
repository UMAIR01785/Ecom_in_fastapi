
from decimal import Decimal
import logging

from langchain_core.tools import tool
from sqlalchemy.orm import Session

from app.services.product_search_service import (
    search_products,
    build_shopping_product_response,
)

logger = logging.getLogger(__name__)

MAX_SEARCH_RESULTS = 8
MAX_QUANTITY = 20


def create_customer_product_tools(
    db: Session,
    cart=None,
):
    """
    Create customer shopping tools.

    db:
        Existing SQLAlchemy session.

    cart:
        Trusted cart object resolved by the existing FastAPI endpoint.
        Never let the AI choose another customer's cart.
    """

    @tool
    def search_shoes(
        keyword: str | None = None,
        color: str | None = None,
        category: str | None = None,
        min_price: float | None = None,
        max_price: float | None = None,
        limit: int = 8,
    ) -> dict:
        """Search the real product database for shoes by keyword,
        color, category, and price range. Use for product discovery.
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
        """Get current details for a product, including its available
        variants, sizes, colors, prices, and stock where available."""

        if product_id <= 0:
            return {"success": False, "message": "Invalid product ID."}

        try:
            # Reuse the existing product search service.
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
        """Add a product to the current customer's cart.
        Use a real product ID and, when applicable, its selected variant ID.
        Ask the customer to choose a size or color when needed."""

        if cart is None:
            return {
                "success": False,
                "message": "Cart context is not configured for this request.",
            }

        if product_id <= 0:
            return {"success": False, "message": "Invalid product ID."}

        if quantity < 1 or quantity > MAX_QUANTITY:
            return {
                "success": False,
                "message": "Quantity must be between 1 and 20.",
            }

        if variant_id is not None and variant_id <= 0:
            return {"success": False, "message": "Invalid variant ID."}

        # TODO: Connect to your existing cart service.
        # Pass the trusted cart, product_id, quantity, and variant_id.
        # That service must validate product/variant ownership,
        # active status, stock, and quantity before writing to the DB.
        return {
            "success": False,
            "message": (
                "Cart service adapter is not connected yet. "
                "Connect this function to your existing cart service."
            ),
        }

    @tool
    def get_cart() -> dict:
        """Retrieve the current customer's cart items and total."""

        if cart is None:
            return {
                "success": False,
                "message": "Cart context is not configured for this request.",
            }

        # TODO: Call your existing cart retrieval service.
        # Return actual items, selected variants, quantities, prices,
        # and totals from the database.
        return {
            "success": False,
            "message": (
                "Cart retrieval adapter is not connected yet. "
                "Connect this function to your existing cart service."
            ),
        }

    @tool
    def update_cart_item(
        cart_item_id: int,
        quantity: int,
    ) -> dict:
        """Update the quantity of an existing item in the current cart."""

        if cart is None:
            return {
                "success": False,
                "message": "Cart context is not configured for this request.",
            }

        if cart_item_id <= 0:
            return {"success": False, "message": "Invalid cart item ID."}

        if quantity < 1 or quantity > MAX_QUANTITY:
            return {
                "success": False,
                "message": "Quantity must be between 1 and 20.",
            }

        # TODO: Call the existing cart update service.
        # Verify that the item belongs to this cart and recheck stock.
        return {
            "success": False,
            "message": (
                "Cart update adapter is not connected yet. "
                "Connect this function to your existing cart service."
            ),
        }

    @tool
    def remove_from_cart(cart_item_id: int) -> dict:
        """Remove an item from the current customer's cart."""

        if cart is None:
            return {
                "success": False,
                "message": "Cart context is not configured for this request.",
            }

        if cart_item_id <= 0:
            return {"success": False, "message": "Invalid cart item ID."}

        # TODO: Call the existing cart removal service.
        # Verify that the item belongs to this cart before deleting it.
        return {
            "success": False,
            "message": (
                "Cart removal adapter is not connected yet. "
                "Connect this function to your existing cart service."
            ),
        }

    return [
        search_shoes,
        get_product_details,
        add_to_cart,
        get_cart,
        update_cart_item,
        remove_from_cart,
    ]
