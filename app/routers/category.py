from app.utils.slug import generate_slug

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    HTTPException,
    UploadFile,
    status,
)
from sqlalchemy.orm import Session

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


# ============================================================
# Get ALL Categories
# Admin Only
#
# Returns both:
# - Active categories
# - Inactive categories
# ============================================================


@router.get(
    "/admin/all",
    response_model=list[CategoryResponse],
)
def get_all_categories(
    db: Session = Depends(get_db),
    current_user: User = Depends(admin_required),
):
    categories = (
        db.query(Category)
        .order_by(Category.id.desc())
        .all()
    )

    return categories


# ============================================================
# Create Category
# Admin Only
#
# Request type:
# multipart/form-data
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
    db: Session = Depends(get_db),
):

    # --------------------------------------------------------
    # Clean category name
    # --------------------------------------------------------

    name = name.strip()

    if not name:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Category name cannot be empty",
        )

    # --------------------------------------------------------
    # Generate slug
    # --------------------------------------------------------

    slug = generate_slug(name)

    if not slug:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid category name",
        )

    # --------------------------------------------------------
    # Check duplicate category
    # --------------------------------------------------------

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

    # --------------------------------------------------------
    # Upload image
    # --------------------------------------------------------

    image_url = None

    if image:
        image_url = await upload_category_image(image)

    # --------------------------------------------------------
    # Create category
    # --------------------------------------------------------

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


# ============================================================
# Update Category
# Admin Only
#
# URL:
# PATCH /categories/admin/{slug}
#
# Admin can update:
# - name
# - description
# - is_active
# - image
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
    db: Session = Depends(get_db),
):

    # --------------------------------------------------------
    # Find category using slug
    #
    # IMPORTANT:
    # Do NOT filter by is_active here.
    #
    # Admin must be able to edit inactive categories too.
    # --------------------------------------------------------

    category = (
        db.query(Category)
        .filter(Category.slug == slug)
        .first()
    )

    if not category:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Category not found",
        )

    # --------------------------------------------------------
    # Update name and slug
    # --------------------------------------------------------

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

        # ----------------------------------------------------
        # Check whether another category already
        # has this name or slug
        # ----------------------------------------------------

        existing_category = (
            db.query(Category)
            .filter(
                Category.id != category.id,
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

    # --------------------------------------------------------
    # Update description
    # --------------------------------------------------------

    if description is not None:
        category.description = description

    # --------------------------------------------------------
    # Update active status
    # --------------------------------------------------------

    if is_active is not None:
        category.is_active = is_active

    # --------------------------------------------------------
    # Update image
    # --------------------------------------------------------

    if image:
        image_url = await upload_category_image(image)

        category.image = image_url

    # --------------------------------------------------------
    # Save changes
    # --------------------------------------------------------

    db.commit()
    db.refresh(category)

    return category


# ============================================================
# Delete Category
# Admin Only
#
# URL:
# DELETE /categories/admin/{slug}
# ============================================================


@router.delete(
    "/admin/{slug}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def delete_category(
    slug: str,
    current_user: User = Depends(admin_required),
    db: Session = Depends(get_db),
):

    # --------------------------------------------------------
    # Find category using slug
    # --------------------------------------------------------

    category = (
        db.query(Category)
        .filter(Category.slug == slug)
        .first()
    )

    if not category:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Category not found",
        )

    # --------------------------------------------------------
    # Delete category
    # --------------------------------------------------------

    db.delete(category)
    db.commit()

    return None


# ============================================================
# PUBLIC / CUSTOMER ROUTES
# ============================================================


# ============================================================
# Get All Active Categories
#
# Public:
# - Non-authenticated users
# - Customers
# - Admins
#
# Only active categories are returned.
# ============================================================


@router.get(
    "/",
    response_model=list[CategoryResponse],
)
def get_active_categories(
    db: Session = Depends(get_db),
):

    categories = (
        db.query(Category)
        .filter(
            Category.is_active.is_(True)
        )
        .order_by(Category.id.desc())
        .all()
    )

    return categories


# ============================================================
# Get Single Active Category
#
# Public:
# - Non-authenticated users
# - Customers
# - Admins
#
# URL:
# GET /categories/{slug}
#
# Inactive categories return 404.
# ============================================================


@router.get(
    "/{slug}",
    response_model=CategoryResponse,
)
def get_active_category(
    slug: str,
    db: Session = Depends(get_db),
):

    category = (
        db.query(Category)
        .filter(
            Category.slug == slug,
            Category.is_active.is_(True),
        )
        .first()
    )

    if not category:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Category not found",
        )

    return category
