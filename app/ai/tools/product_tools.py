from sqlalchemy.orm import Session
from langchain_core.tools import tool

from app.models.product import Product


def create_product_tools(db: Session):
    @tool
    def list_products(limit: int = 10) -> dict:
        """List active products. Limit must be between 1 and 20."""
        if not 1 <= limit <= 20:
            return {"error": "Limit must be between 1 and 20"}

        products = (
            db.query(Product)
            .filter(Product.is_active.is_(True))
            .order_by(Product.id.desc())
            .limit(limit)
            .all()
        )

        return {
            "products": [
                {
                    "id": product.id,
                    "name": product.name,
                    "stock": product.stock,
                    "is_active": product.is_active,
                }
                for product in products
            ]
        }

    @tool
    def get_low_stock_products(
        threshold: int = 5,
        limit: int = 10,
    ) -> dict:
        """Find active products with stock at or below threshold."""
        if not 0 <= threshold <= 1000:
            return {"error": "Threshold must be between 0 and 1000"}

        if not 1 <= limit <= 20:
            return {"error": "Limit must be between 1 and 20"}

        products = (
            db.query(Product)
            .filter(
                Product.is_active.is_(True),
                Product.stock <= threshold,
            )
            .order_by(Product.stock.asc(), Product.id.asc())
            .limit(limit)
            .all()
        )

        return {
            "threshold": threshold,
            "products": [
                {
                    "id": product.id,
                    "name": product.name,
                    "stock": product.stock,
                }
                for product in products
            ],
        }

    @tool
    def update_product_stock(
        product_id: int,
        quantity_change: int,
    ) -> dict:
        """Adjust product stock by a positive or negative quantity.
        Use only when the admin has authorized the adjustment.
        """
        if quantity_change == 0:
            return {"error": "Quantity change cannot be zero"}

        if abs(quantity_change) > 10000:
            return {"error": "Quantity change is too large"}

        product = (
            db.query(Product)
            .filter(Product.id == product_id)
            .with_for_update()
            .first()
        )

        if not product:
            return {"error": "Product not found"}

        new_stock = product.stock + quantity_change

        if new_stock < 0:
            return {"error": "Stock cannot become negative"}

        old_stock = product.stock

        try:
            product.stock = new_stock
            db.commit()
            db.refresh(product)
        except Exception:
            db.rollback()
            raise

        return {
            "success": True,
            "product_id": product.id,
            "old_stock": old_stock,
            "new_stock": product.stock,
        }

    return [
        list_products,
        get_low_stock_products,
        update_product_stock,
    ]