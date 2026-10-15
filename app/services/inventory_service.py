
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

    await manager.send_to_admin({
        "type": "inventory_updated",
        "reason": reason,
        "order_id": order_id,
        "products": [
            {
                "product_id": product.id,
                "product_name": product.name,
                "stock": product.stock,
            }
            for product in products
        ],
    })
