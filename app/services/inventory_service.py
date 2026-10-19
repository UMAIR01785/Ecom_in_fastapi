from app.models.product import Product
from app.websockets.manager import manager


async def publish_inventory_updates(
    products: list[Product],
    *,
    reason: str,
    order_id: int | None = None,
) -> None:
    if not products:
        return

    product_data = [
        {
            "product_id": product.id,
            "product_name": product.name,
            "stock": product.stock,
        }
        for product in products
    ]

    # Existing admin inventory event
    await manager.send_to_admin({
        "type": "inventory_updated",
        "reason": reason,
        "order_id": order_id,
        "products": product_data,
    })

    # New public catalog notification
    await manager.broadcast_to_catalog({
        "type": "catalog_updated",
        "entity": "product",
        "action": "updated",
        "ids": [product.id for product in products],
        "reason": reason,
    })