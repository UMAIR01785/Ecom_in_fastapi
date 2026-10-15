"""Seed the database with fake categories, products (and optionally orders).

Usage:
    python -m app.scripts.seed_data            # seed (skips if data exists)
    python -m app.scripts.seed_data --force    # wipe categories/products first
    python -m app.scripts.seed_data --orders   # also seed 10 fake orders
"""

import argparse
import random
from decimal import Decimal

from faker import Faker

from app.database import SessionLocal
from app.models import Category, Product, Order, User
from app.models.order import OrderItem, OrderStatus
from app.models.user import UserRole
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
    "Wireless Headphones", "Smart Watch", "Laptop Stand", "USB-C Hub", "Bluetooth Speaker",
    "Cotton T-Shirt", "Denim Jeans", "Hooded Sweatshirt", "Summer Dress", "Wool Cardigan",
    "Non-Stick Pan", "Coffee Maker", "Storage Organizer", "LED Desk Lamp", "Chef's Knife",
    "Running Shoes", "Yoga Mat", "Cycling Helmet", "Dumbbell Set", "Resistance Bands",
    "Face Moisturizer", "Vitamin C Serum", "Sunscreen SPF 50", "Lip Balm", "Hair Dryer",
    "Hardcover Novel", "Notebook Set", "Fountain Pen", "Cookbook", "Puzzle 1000pcs",
    "Building Blocks", "Board Game", "Remote-Control Car", "Plush Bear", "Art Kit",
    "Leather Wallet", "Canvas Backpack", "Sunglasses", "Belt", "Tote Bag",
    "Granola Bars", "Coffee Beans", "Olive Oil", "Green Tea", "Dark Chocolate",
    "Ceramic Mug", "Throw Blanket", "Scented Candle", "Wall Clock", "Plant Pot",
]


def _unique_slug(name: str, used: set) -> str:
    slug = generate_slug(name)
    base = slug
    i = 2
    while slug in used:
        slug = f"{base}-{i}"
        i += 1
    used.add(slug)
    return slug


def seed_categories(db) -> list[Category]:
    existing = db.query(Category).all()
    if existing:
        print(f"Categories: {len(existing)} already exist - reusing them.")
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
    db.commit()
    print(f"Seeded {len(CATEGORIES)} categories.")
    return db.query(Category).all()


def seed_products(db, categories: list[Category]) -> list[Product]:
    existing_count = db.query(Product).count()
    if existing_count:
        print(f"Products: {existing_count} already exist - skipping.")
        return db.query(Product).all()

    used_slugs: set = set()
    total = len(PRODUCT_NOUNS)
    for i, noun in enumerate(PRODUCT_NOUNS):
        name = f"{fake.last_name()} {noun}"
        product = Product(
            name=name,
            slug=_unique_slug(name, used_slugs),
            description=fake.paragraph(nb_sentences=3),
            price=Decimal(str(round(random.uniform(10, 500), 2))),
            stock=random.randint(0, 100),
            is_active=True,
        )
        primary = categories[(i * len(categories)) // total]
        assigned = [primary]
        if random.random() < 0.3:
            secondary = random.choice(categories)
            if secondary is not primary:
                assigned.append(secondary)
        product.categories = assigned
        db.add(product)
    db.commit()
    print(f"Seeded {len(PRODUCT_NOUNS)} products.")
    return db.query(Product).all()


def seed_orders(db, n: int = 10) -> None:
    if db.query(Order).count():
        print("Orders already exist - skipping.")
        return

    customers = db.query(User).filter(User.role == UserRole.CUSTOMER).all()
    if not customers:
        print("Orders: no customer users found - skipping.")
        return

    products = db.query(Product).all()
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
        db.flush()

        total = Decimal("0.00")
        for product in random.sample(products, k=random.randint(1, 4)):
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

    db.commit()
    print(f"Seeded {n} orders.")


def main() -> None:
    parser = argparse.ArgumentParser(description="Seed fake store data")
    parser.add_argument(
        "--force",
        action="store_true",
        help="Delete existing categories and products first",
    )
    parser.add_argument(
        "--orders",
        action="store_true",
        help="Also seed 10 fake orders for existing customers",
    )
    args = parser.parse_args()

    db = SessionLocal()
    try:
        if args.force:
            try:
                db.query(Product).delete(synchronize_session=False)
                db.query(Category).delete(synchronize_session=False)
                db.commit()
                print("Cleared existing categories and products.")
            except Exception as e:
                db.rollback()
                print(f"Could not clear data (orders may reference products): {e}")

        categories = seed_categories(db)
        seed_products(db, categories)

        if args.orders:
            seed_orders(db)

        print("\n=== Database summary ===")
        print(f"Categories: {db.query(Category).count()}")
        print(f"Products:   {db.query(Product).count()}")
        print(f"Orders:     {db.query(Order).count()}")

        print("\nSample categories:")
        for c in db.query(Category).limit(3):
            print(f"  - {c.name} (/{c.slug})")

        print("\nSample products:")
        for p in db.query(Product).limit(5):
            cats = ", ".join(c.name for c in p.categories)
            print(f"  - {p.name} | ${p.price} | stock {p.stock} | {cats}")
    finally:
        db.close()


if __name__ == "__main__":
    main()
