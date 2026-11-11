
"""
Seed database with fake categories, products, variants and orders.

Usage:
    python -m app.scripts.seed_data
    python -m app.scripts.seed_data --products
    python -m app.scripts.seed_data --force
    python -m app.scripts.seed_data --orders
"""

import argparse
import asyncio
import random
from decimal import Decimal

from faker import Faker
from sqlalchemy import select, delete, func
from sqlalchemy.orm import selectinload

from app.database import SessionLocal
from app.models import Category, Product, Order, User
from app.models.order import OrderItem, OrderStatus
from app.models.user import UserRole
from app.models.product_variant import ProductVariant
from app.utils.slug import generate_slug

fake = Faker()


CATEGORIES = [
    ("Electronics", "Phones, laptops, gadgets and accessories"),
    ("Clothing", "Men's and women's apparel"),
    ("Home & Kitchen", "Appliances, cookware and home essentials"),
    ("Sports", "Sportswear, fitness gear and outdoor equipment"),
    ("Beauty", "Skincare, makeup and personal care"),
    ("Books", "Fiction, non-fiction and academic titles"),
    ("Toys", "Toys, games and collectibles"),
    ("Footwear", "Shoes, sneakers and sandals"),
    ("Accessories", "Bags, wallets, watches and jewelry"),
    ("Grocery", "Snacks, beverages and pantry staples"),
]


PRODUCT_NOUNS = [
    "Wireless Headphones", "Smart Watch", "Laptop Stand",
    "USB-C Hub", "Bluetooth Speaker", "Cotton T-Shirt",
    "Denim Jeans", "Hooded Sweatshirt", "Summer Dress",
    "Wool Cardigan", "Non-Stick Pan", "Coffee Maker",
    "Storage Organizer", "LED Desk Lamp", "Chef's Knife",
    "Running Shoes", "Yoga Mat", "Cycling Helmet",
    "Dumbbell Set", "Resistance Bands", "Face Moisturizer",
    "Vitamin C Serum", "Sunscreen SPF 50", "Lip Balm",
    "Hair Dryer", "Hardcover Novel", "Notebook Set",
    "Fountain Pen", "Cookbook", "Puzzle 1000pcs",
    "Building Blocks", "Board Game", "Remote-Control Car",
    "Plush Bear", "Art Kit", "Leather Wallet",
    "Canvas Backpack", "Sunglasses", "Belt", "Tote Bag",
    "Granola Bars", "Coffee Beans", "Olive Oil",
    "Green Tea", "Dark Chocolate", "Ceramic Mug",
    "Throw Blanket", "Scented Candle", "Wall Clock",
    "Plant Pot",
]


PRODUCT_TYPES = {
    "clothing": [
        "Cotton T-Shirt", "Denim Jeans", "Hooded Sweatshirt",
        "Summer Dress", "Wool Cardigan",
    ],
    "footwear": ["Running Shoes"],
    "electronics": [
        "Wireless Headphones", "Smart Watch", "Laptop Stand",
        "USB-C Hub", "Bluetooth Speaker",
    ],
    "home": [
        "Non-Stick Pan", "Coffee Maker", "Storage Organizer",
        "LED Desk Lamp", "Chef's Knife", "Ceramic Mug",
        "Throw Blanket", "Scented Candle", "Wall Clock",
        "Plant Pot",
    ],
    "sports": [
        "Yoga Mat", "Cycling Helmet", "Dumbbell Set",
        "Resistance Bands",
    ],
    "beauty": [
        "Face Moisturizer", "Vitamin C Serum",
        "Sunscreen SPF 50", "Lip Balm", "Hair Dryer",
    ],
    "books": [
        "Hardcover Novel", "Notebook Set", "Fountain Pen",
        "Cookbook",
    ],
    "toys": [
        "Puzzle 1000pcs", "Building Blocks", "Board Game",
        "Remote-Control Car", "Plush Bear", "Art Kit",
    ],
    "accessories": [
        "Leather Wallet", "Canvas Backpack", "Sunglasses",
        "Belt", "Tote Bag",
    ],
    "grocery": [
        "Granola Bars", "Coffee Beans", "Olive Oil",
        "Green Tea", "Dark Chocolate",
    ],
}


VARIANT_CONFIG = {
    "clothing": {
        "sizes": ["S", "M", "L", "XL"],
        "colors": ["Black", "White", "Blue", "Red"],
    },
    "footwear": {
        "sizes": ["38", "39", "40", "41", "42", "43", "44"],
        "colors": ["Black", "White", "Brown"],
    },
    "electronics": {
        "sizes": ["64GB", "128GB", "256GB", "Standard"],
        "colors": ["Black", "Silver", "White"],
    },
    "home": {
        "sizes": ["Small", "Medium", "Large"],
        "colors": ["Black", "White", "Silver", "Brown"],
    },
    "sports": {
        "sizes": ["S", "M", "L", "XL"],
        "colors": ["Black", "Blue", "Red"],
    },
    "beauty": {
        "sizes": ["30ml", "50ml", "100ml"],
        "colors": ["Standard", "Pink", "Natural"],
    },
    "books": {
        "sizes": ["Paperback", "Hardcover"],
        "colors": ["Standard"],
    },
    "toys": {
        "sizes": ["Small", "Medium", "Large"],
        "colors": ["Red", "Blue", "Yellow"],
    },
    "accessories": {
        "sizes": ["Small", "Medium", "Large"],
        "colors": ["Black", "Brown", "Blue", "White"],
    },
    "grocery": {
        "sizes": ["250g", "500g", "1kg"],
        "colors": ["Standard"],
    },
}


def unique_slug(name: str, used: set) -> str:
    slug = generate_slug(name)
    base = slug
    i = 2

    while slug in used:
        slug = f"{base}-{i}"
        i += 1

    used.add(slug)
    return slug


def get_variant_options(noun: str) -> list[tuple[str, str]]:
    category = next(
        (
            category
            for category, products in PRODUCT_TYPES.items()
            if noun in products
        ),
        "home",
    )

    config = VARIANT_CONFIG[category]

    combinations = [
        (size, color)
        for size in config["sizes"]
        for color in config["colors"]
    ]

    return random.sample(
        combinations,
        k=min(len(combinations), random.randint(3, 6)),
    )


def generate_variant_sku(
    product_slug: str,
    size: str,
    color: str,
    used_skus: set[str],
) -> str:

    base = (
        f"{product_slug}-{generate_slug(size)}-"
        f"{generate_slug(color)}"
    ).upper()

    sku = base[:100]
    counter = 2

    while sku in used_skus:
        suffix = f"-{counter}"
        sku = base[:100 - len(suffix)] + suffix
        counter += 1

    used_skus.add(sku)
    return sku


async def seed_categories(db) -> list[Category]:

    result = await db.execute(select(Category))
    existing = result.scalars().all()

    if existing:
        print(
            f"Categories: {len(existing)} already exist - reusing them."
        )
        return existing

    for name, description in CATEGORIES:
        db.add(
            Category(
                name=name,
                slug=generate_slug(name),
                description=description,
                is_active=True,
            )
        )

    await db.flush()

    result = await db.execute(select(Category))
    categories = result.scalars().all()

    print(f"Seeded {len(categories)} categories.")

    return categories


async def seed_products(
    db,
    categories: list[Category],
    force: bool = False,
) -> list[Product]:

    result = await db.execute(
        select(func.count()).select_from(Product)
    )
    existing_count = result.scalar_one()

    if existing_count and not force:
        print(
            f"Products: {existing_count} already exist - skipping."
        )

        result = await db.execute(
            select(Product).options(
                selectinload(Product.categories),
                selectinload(Product.variants),
            )
        )

        return result.scalars().all()

    if not categories:
        print("No categories available. Skipping products.")
        return []

    result = await db.execute(select(Product.slug))
    used_slugs = set(result.scalars().all())

    result = await db.execute(select(ProductVariant.sku))
    used_skus = set(result.scalars().all())

    total = len(PRODUCT_NOUNS)
    variant_count = 0

    for i, noun in enumerate(PRODUCT_NOUNS):

        name = f"{fake.last_name()} {noun}"

        product = Product(
            name=name,
            slug=unique_slug(name, used_slugs),
            description=fake.paragraph(nb_sentences=3),
            price=Decimal(
                str(round(random.uniform(10, 500), 2))
            ),
            stock=0,
            is_active=True,
        )

        primary = categories[
            (i * len(categories)) // total
        ]

        assigned = [primary]

        if random.random() < 0.3:
            secondary = random.choice(categories)

            if secondary is not primary:
                assigned.append(secondary)

        product.categories = assigned

        db.add(product)

        await db.flush()

        options = get_variant_options(noun)
        total_variant_stock = 0

        for size, color in options:

            stock = random.randint(5, 30)

            variant = ProductVariant(
                product_id=product.id,
                sku=generate_variant_sku(
                    product.slug,
                    size,
                    color,
                    used_skus,
                ),
                size=size,
                color=color,
                price=None,
                stock=stock,
                is_active=True,
            )

            db.add(variant)

            total_variant_stock += stock
            variant_count += 1

        product.stock = total_variant_stock

    await db.flush()

    print(f"Seeded {total} products.")
    print(f"Seeded {variant_count} product variants.")

    result = await db.execute(
        select(Product).options(
            selectinload(Product.categories),
            selectinload(Product.variants),
        )
    )

    return result.scalars().all()


async def seed_orders(db, n: int = 10) -> None:

    result = await db.execute(
        select(func.count()).select_from(Order)
    )

    if result.scalar_one():
        print("Orders already exist - skipping.")
        return

    result = await db.execute(
        select(User).where(User.role == UserRole.CUSTOMER)
    )
    customers = result.scalars().all()

    if not customers:
        print("Orders: no customer users found - skipping.")
        return

    result = await db.execute(select(Product))
    products = result.scalars().all()

    if not products:
        print("Orders: no products found - skipping.")
        return

    for _ in range(n):

        order = Order(
            user_id=random.choice(customers).id,
            total_amount=Decimal("0.00"),
            status=random.choice(list(OrderStatus)),
        )

        db.add(order)
        await db.flush()

        total = Decimal("0.00")

        selected_products = random.sample(
            products,
            k=random.randint(1, min(4, len(products))),
        )

        for product in selected_products:

            quantity = random.randint(1, 3)
            total += product.price * quantity

            db.add(
                OrderItem(
                    order_id=order.id,
                    product_id=product.id,
                    quantity=quantity,
                    unit_price=product.price,
                )
            )

        order.total_amount = total

    await db.flush()

    print(f"Seeded {n} orders.")


async def print_summary(db):

    async def get_count(model):
        result = await db.execute(
            select(func.count()).select_from(model)
        )
        return result.scalar_one()

    print("\n=== Database summary ===")

    print(f"Categories: {await get_count(Category)}")
    print(f"Products:   {await get_count(Product)}")
    print(f"Variants:   {await get_count(ProductVariant)}")
    print(f"Orders:     {await get_count(Order)}")

    print("\nSample categories:")

    result = await db.execute(
        select(Category).limit(3)
    )

    for category in result.scalars().all():
        print(f"  - {category.name} (/{category.slug})")

    print("\nSample products with variants:")

    result = await db.execute(
        select(Product)
        .options(
            selectinload(Product.categories),
            selectinload(Product.variants),
        )
        .limit(5)
    )

    for product in result.scalars().all():

        print(f"\nProduct: {product.name}")
        print(f"Price: ${product.price}")
        print(f"Total Stock: {product.stock}")

        print("Variants:")

        for variant in product.variants:

            effective_price = (
                variant.price
                if variant.price is not None
                else product.price
            )

            print(
                f"  SKU: {variant.sku} | "
                f"Size: {variant.size} | "
                f"Color: {variant.color} | "
                f"Price: ${effective_price} | "
                f"Stock: {variant.stock}"
            )


async def main():

    parser = argparse.ArgumentParser(
        description="Seed fake store data"
    )

    parser.add_argument(
        "--force",
        action="store_true",
        help="Delete existing categories and products first",
    )

    parser.add_argument(
        "--products",
        action="store_true",
        help="Add products even if some already exist",
    )

    parser.add_argument(
        "--orders",
        action="store_true",
        help="Also seed 10 fake orders",
    )

    args = parser.parse_args()

    async with SessionLocal() as db:

        try:

            if args.force:

                try:
                    async with db.begin_nested():

                        # Delete variants before their parent products.
                        await db.execute(
                            delete(ProductVariant)
                        )

                        await db.execute(
                            delete(Product)
                        )

                        await db.execute(
                            delete(Category)
                        )

                    print(
                        "Cleared existing categories, products "
                        "and variants."
                    )

                except Exception as e:
                    print(f"Could not clear existing data: {e}")

            categories = await seed_categories(db)

            await seed_products(
                db,
                categories,
                force=args.products or args.force,
            )

            if args.orders:
                await seed_orders(db)

            await db.commit()

            await print_summary(db)

        except Exception as e:

            await db.rollback()

            print(f"\nError seeding database: {e}")
            raise


if __name__ == "__main__":
    asyncio.run(main())
