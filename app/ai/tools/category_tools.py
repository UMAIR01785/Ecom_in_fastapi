
import re

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from langchain_core.tools import tool

from app.models.category import Category


def create_category_tools(db: AsyncSession):

    @tool
    async def list_categories(limit: int = 20) -> dict:
        """List available product categories."""

        if not 1 <= limit <= 50:
            return {"error": "Limit must be between 1 and 50"}

        result = await db.execute(
            select(Category)
            .order_by(Category.id.asc())
            .limit(limit)
        )

        categories = result.scalars().all()

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
    async def create_category(name: str) -> dict:
        """Create a category after validating its name."""

        name = name.strip()

        if not name or len(name) > 100:
            return {
                "error": "Category name must be between 1 and 100 characters"
            }

        slug = re.sub(
            r"[^a-z0-9]+",
            "-",
            name.lower()
        ).strip("-")

        if not slug:
            return {
                "error": "Could not generate a valid category slug"
            }

        result = await db.execute(
            select(Category).where(Category.slug == slug)
        )

        existing = result.scalar_one_or_none()

        if existing:
            return {
                "error": "A category with this slug already exists"
            }

        category = Category(
            name=name,
            slug=slug
        )

        try:
            db.add(category)

            await db.commit()
            await db.refresh(category)

        except IntegrityError:
            await db.rollback()
            return {
                "error": "Category already exists or violates a database constraint"
            }

        except Exception:
            await db.rollback()
            raise

        return {
            "success": True,
            "id": category.id,
            "name": category.name,
            "slug": category.slug,
        }

    return [list_categories, create_category]
