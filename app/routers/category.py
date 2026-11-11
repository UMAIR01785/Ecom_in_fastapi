
import json

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    HTTPException,
    UploadFile,
    status,
    Response,
)
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.utils.slug import generate_slug
from app.websockets.manager import manager
from app.core.redis import redis_client
from app.core.cloudinary import upload_category_image
from app.database import get_db
from app.dependencies.permissions import admin_required
from app.models.category import Category
from app.models.user import User
from app.schemas.category import CategoryResponse


router = APIRouter(
    prefix="/categories",
    tags=["Categories"],
)


# ============================================================
# ADMIN ROUTES
# ============================================================


# Get ALL Categories - Admin Only
@router.get(
    "/admin/all",
    response_model=list[CategoryResponse],
)
async def get_all_categories(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(admin_required),
):
    result = await db.execute(
        select(Category).order_by(Category.id.desc())
    )

    categories = result.scalars().all()

    return categories


# ============================================================
# Create Category - Admin Only
# ============================================================

@router.post(
    "/admin",
    response_model=CategoryResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_category(
    name: str = Form(...),
    description: str | None = Form(None),
    image: UploadFile | None = File(None),
    current_user: User = Depends(admin_required),
    db: AsyncSession = Depends(get_db),
):
    name = name.strip()

    if not name:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Category name cannot be empty",
        )

    slug = generate_slug(name)

    if not slug:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid category name",
        )

    # Check duplicate category
    result = await db.execute(
        select(Category).where(
            (Category.name == name)
            | (Category.slug == slug)
        )
    )

    existing_category = result.scalar_one_or_none()

    if existing_category:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Category name or slug already exists",
        )

    # Upload image
    image_url = None

    if image:
        image_url = await upload_category_image(image)

    # Create category
    category = Category(
        name=name,
        slug=slug,
        description=description,
        image=image_url,
    )

    db.add(category)

    try:
        await db.commit()
        await db.refresh(category)
    except Exception:
        await db.rollback()
        raise

    # Clear cached active categories
    await redis_client.delete("categories:active")

    await manager.broadcast_to_catalog({
        "type": "catalog_updated",
        "entity": "category",
        "action": "created",
        "id": category.id,
    })

    return category


# ============================================================
# Update Category - Admin Only
# ============================================================

@router.patch(
    "/admin/{slug}",
    response_model=CategoryResponse,
)
async def update_category(
    slug: str,
    name: str | None = Form(None),
    description: str | None = Form(None),
    is_active: bool | None = Form(None),
    image: UploadFile | None = File(None),
    current_user: User = Depends(admin_required),
    db: AsyncSession = Depends(get_db),
):
    # Find category, including inactive categories
    result = await db.execute(
        select(Category).where(Category.slug == slug)
    )

    category = result.scalar_one_or_none()

    if not category:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Category not found",
        )

    # Update name and slug
    if name is not None:
        name = name.strip()

        if not name:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Category name cannot be empty",
            )

        new_slug = generate_slug(name)

        if not new_slug:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid category name",
            )

        # Check whether another category has this name or slug
        result = await db.execute(
            select(Category).where(
                Category.id != category.id,
                (
                    (Category.name == name)
                    | (Category.slug == new_slug)
                ),
            )
        )

        existing_category = result.scalar_one_or_none()

        if existing_category:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Category name or slug already exists",
            )

        category.name = name
        category.slug = new_slug

    # Update description
    if description is not None:
        category.description = description

    # Update active status
    if is_active is not None:
        category.is_active = is_active

    # Update image
    if image:
        image_url = await upload_category_image(image)
        category.image = image_url

    try:
        await db.commit()
        await db.refresh(category)
    except Exception:
        await db.rollback()
        raise

    # Clear cached active categories
    await redis_client.delete("categories:active")

    await manager.broadcast_to_catalog({
        "type": "catalog_updated",
        "entity": "category",
        "action": "updated",
        "id": category.id,
    })

    return category


# ============================================================
# Delete Category - Admin Only
# ============================================================

@router.delete(
    "/admin/{slug}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_category(
    slug: str,
    current_user: User = Depends(admin_required),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Category).where(Category.slug == slug)
    )

    category = result.scalar_one_or_none()

    if not category:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Category not found",
        )

    category_id = category.id

    try:
        await db.delete(category)
        await db.commit()
    except Exception:
        await db.rollback()
        raise

    # Clear cached active categories
    await redis_client.delete("categories:active")

    await manager.broadcast_to_catalog({
        "type": "catalog_updated",
        "entity": "category",
        "action": "deleted",
        "id": category_id,
    })

    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ============================================================
# PUBLIC / CUSTOMER ROUTES
# ============================================================


# Get All Active Categories
@router.get(
    "/",
    response_model=list[CategoryResponse],
)
async def get_active_categories(
    response: Response,
    db: AsyncSession = Depends(get_db),
):
    cache_key = "categories:active"

    cached_categories = await redis_client.get(cache_key)

    if cached_categories is not None:
        response.headers["X-Cache"] = "HIT"
        return json.loads(cached_categories)

    result = await db.execute(
        select(Category)
        .where(Category.is_active.is_(True))
        .order_by(Category.id.desc())
    )

    categories = result.scalars().all()

    result_data = [
        CategoryResponse.model_validate(category).model_dump(mode="json")
        for category in categories
    ]

    await redis_client.set(
        cache_key,
        json.dumps(result_data),
        ex=600,
    )

    response.headers["X-Cache"] = "MISS"

    return result_data


# ============================================================
# Get Single Active Category
# ============================================================

@router.get(
    "/{slug}",
    response_model=CategoryResponse,
)
async def get_active_category(
    slug: str,
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Category).where(
            Category.slug == slug,
            Category.is_active.is_(True),
        )
    )

    category = result.scalar_one_or_none()

    if not category:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Category not found",
        )

    return category
