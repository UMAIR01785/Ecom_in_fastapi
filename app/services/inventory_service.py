
from app.models.product import Product
from app.models.product_variant import ProductVariant
from app.websockets.manager import manager


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
