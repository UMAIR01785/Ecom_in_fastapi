#!/usr/bin/env python3
"""Simple script to generate fake categories and products using faker"""
import random
from faker import Faker

fake = Faker()

def generate_categories(n=5):
    """Generate n fake categories"""
    categories = []
    for _ in range(n):
        category = {
            "name": fake.word().capitalize(),
            "slug": fake.slug(),
            "description": fake.text(max_nb_chars=150),
            "is_active": True
        }
        categories.append(category)
    return categories

def generate_products(n=20, categories=None):
    """Generate n fake products, optionally linked to categories"""
    products = []
    if categories is None:
        categories = [{"name": f"Category {i+1}"} for i in range(5)]
    
    for _ in range(n):
        product = {
            "name": fake.word().capitalize() + " " + fake.last_name(),
            "description": fake.text(max_nb_chars=200),
            "price": round(random.uniform(10, 500), 2),
            "category": random.choice(categories)["name"],
            "stock": random.randint(0, 100),
            "is_active": True
        }
        products.append(product)
    return products

if __name__ == "__main__":
    print("=" * 60)
    print("FAKE CATEGORIES")
    print("=" * 60)
    categories = generate_categories(5)
    for i, cat in enumerate(categories):
        print(f"{i+1}. Name: {cat['name']}, Slug: {cat['slug']}")
    
    print("\n" + "=" * 60)
    print("FAKE PRODUCTS")
    print("=" * 60)
    products = generate_products(20, categories)
    for i, prod in enumerate(products):
        print(f"{i+1}. Name: {prod['name']}, "
              f"Price: ${prod['price']}, "
              f"Category: {prod['category']}, "
              f"Stock: {prod['stock']}")
    
    print("\n" + "=" * 60)
    print("To add these to your database, use your seed_data.py script")
    print("or integrate the faker functions into your app.")