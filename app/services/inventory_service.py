
from app.models.product import Product
from app.models.product_variant import ProductVariant
from app.websockets.manager import manager
from datetime import datetime
from uuid import uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.invertory_lots import InventoryLot

async def publish_inventory_updates(
    products: list[Product],
    *,
    reason: str,
    order_id: int | None = None,
    variants: list[ProductVariant] | None = None,
) -> None:
    """
    Broadcast inventory changes to the admin dashboard and public catalog.

    Products without variants use product-level stock.
    Products with variants can additionally report stock for each size/color.
    """

    if not products and not variants:
        return

    product_data = [
        {
            "product_id": product.id,
            "product_name": product.name,
            "stock": product.stock,
        }
        for product in (products or [])
    ]

    variant_data = [
        {
            "variant_id": variant.id,
            "product_id": variant.product_id,
            "sku": variant.sku,
            "size": variant.size,
            "color": variant.color,
            "price": (
                str(variant.price)
                if variant.price is not None
                else None
            ),
            "stock": variant.stock,
            "is_active": variant.is_active,
        }
        for variant in (variants or [])
    ]

    product_ids = sorted({
        product.id for product in (products or [])
    } | {
        variant.product_id for variant in (variants or [])
    })

    # Notify the admin dashboard.
    await manager.send_to_admin({
        "type": "inventory_updated",
        "reason": reason,
        "order_id": order_id,
        "products": product_data,
        "variants": variant_data,
    })

    # Notify connected public catalog clients.
    await manager.broadcast_to_catalog({
        "type": "catalog_updated",
        "entity": "product",
        "action": "updated",
        "ids": product_ids,
        "reason": reason,
    })


async def receive_product_inventory(
    db: AsyncSession,
    product: Product,
    quantity: int,
    *,
    lot_number: str | None = None,
    expires_at: datetime | None = None,
) -> InventoryLot:
    """
    Receive stock for a standalone product.

    Creates an inventory lot and updates Product.stock.
    The caller is responsible for committing or rolling back.
    """

    if quantity <= 0:
        raise ValueError("Inventory quantity must be greater than zero")

    # Generate a unique lot reference if admin did not provide one.
    if lot_number is None:
        lot_number = (
            f"PRD-{product.id}-{uuid4().hex[:10].upper()}"
        )

    # Create inventory lot.
    lot = InventoryLot(
        lot_number=lot_number,
        product_id=product.id,
        variant_id=None,
        quantity_received=quantity,
        quantity_remaining=quantity,
        expires_at=expires_at,
        received_at=datetime.utcnow(),
    )

    db.add(lot)

    # Update aggregate product stock.
    product.stock += quantity

    await db.flush()

    return lot
