import re

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    HTTPException,
    UploadFile,
    status,
)
from app.dependencies.auth import get_current_user
from sqlalchemy.orm import Session
from app.models.user import UserRole
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


# ==================================================
# Helper Function
# ==================================================

def generate_slug(name: str) -> str:
    slug = name.lower().strip()
    slug = re.sub(r"[^a-z0-9]+", "-", slug)
    slug = slug.strip("-")

    return slug


# ==================================================
# Create Category
# Admin Only
# ==================================================

@router.post(
    "/",
    response_model=CategoryResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_category(
    name: str = Form(...),
    description: str | None = Form(None),
    image: UploadFile | None = File(None),
    current_user: User = Depends(admin_required),
    db: Session = Depends(get_db),
):
    slug = generate_slug(name)

    existing_category = (
        db.query(Category)
        .filter(
            (Category.name == name)
            | (Category.slug == slug)
        )
        .first()
    )

    if existing_category:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Category name or slug already exists",
        )

    image_url = None

    if image:
        image_url = await upload_category_image(image)

    category = Category(
        name=name,
        slug=slug,
        description=description,
        image=image_url,
    )

    db.add(category)
    db.commit()
    db.refresh(category)

    return category


# ==================================================
# Get All Categories
# Public
# ==================================================

@router.get(
    "/",
    response_model=list[CategoryResponse],
)
def get_categories(
    db: Session = Depends(get_db),
):
    categories = (
        db.query(Category)
        .filter(Category.is_active == True)
        .all()
    )

    return categories




# ==================================================
# Get All Categories (Admin)
# Shows all categories including inactive
# ==================================================

@router.get("/admin/all", response_model=list[CategoryResponse])
def get_all_categories(
    db: Session = Depends(get_db),
    current_user: User = Depends(admin_required),
):
    if current_user.role != UserRole.ADMIN:
        raise HTTPException(
            status_code=403,
            detail="Admin access required"
        )

    categories = (
        db.query(Category)
        .order_by(Category.id.desc())
        .all()
    )

    return categories

# ==================================================
# Get Single Category
# Public
# ==================================================

@router.get(
    "/{category_id}",
    response_model=CategoryResponse,
)
def get_category(
    category_id: int,
    db: Session = Depends(get_db),
):
    category = (
        db.query(Category)
        .filter(
            Category.id == category_id,
            Category.is_active == True,
        )
        .first()
    )

    if not category:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Category not found",
        )

    return category


# ==================================================
# Update Category
# Admin Only
# ==================================================

@router.patch(
    "/{category_id}",
    response_model=CategoryResponse,
)
async def update_category(
    category_id: int,
    name: str | None = Form(None),
    description: str | None = Form(None),
    is_active: bool | None = Form(None),
    image: UploadFile | None = File(None),
    current_user: User = Depends(admin_required),
    db: Session = Depends(get_db),
):
    category = (
        db.query(Category)
        .filter(Category.id == category_id)
        .first()
    )

    if not category:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Category not found",
        )

    # Update name and slug
    if name is not None:
        new_slug = generate_slug(name)

        existing_category = (
            db.query(Category)
            .filter(
                Category.id != category_id,
                (
                    (Category.name == name)
                    | (Category.slug == new_slug)
                ),
            )
            .first()
        )

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

    db.commit()
    db.refresh(category)

    return category