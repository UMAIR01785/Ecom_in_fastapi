import re

from sqlalchemy.orm import Session
from langchain_core.tools import tool

from app.models.category import Category


def create_category_tools(db: Session):
    @tool
    def list_categories(limit: int = 20) -> dict:
        """List product categories."""
        if not 1 <= limit <= 50:
            return {"error": "Limit must be between 1 and 50"}

        categories = (
            db.query(Category)
            .order_by(Category.id.asc())
            .limit(limit)
            .all()
        )

        return {
            "categories": [
                {
                    "id": category.id,
                    "name": category.name,
                    "slug": category.slug,
                }
                for category in categories
            ]
        }

    @tool
    def create_category(name: str) -> dict:
        """Create a category after validating its name."""
        name = name.strip()

        if not name or len(name) > 100:
            return {
                "error": "Category name must be between 1 and 100 characters"
            }

        slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")

        if not slug:
            return {"error": "Could not generate a valid category slug"}

        existing = (
            db.query(Category)
            .filter(Category.slug == slug)
            .first()
        )

        if existing:
            return {"error": "A category with this slug already exists"}

        category = Category(name=name, slug=slug)

        try:
            db.add(category)
            db.commit()
            db.refresh(category)
        except Exception:
            db.rollback()
            raise

        return {
            "success": True,
            "id": category.id,
            "name": category.name,
            "slug": category.slug,
        }

    return [list_categories, create_category]