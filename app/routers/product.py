
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

from app.core.cloudinary import upload_product_image
from app.database import get_db
from app.dependencies.permissions import admin_required
from app.models.category import Category
from app.models.product import Product
from app.schemas.product import ProductResponse


router = APIRouter(
    prefix="",
    tags=["Products"],
)


# ============================================================
# CREATE PRODUCT
# ============================================================

@router.post(
    "/",
    response_model=ProductResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_product(
    name: str = Form(...),
    description: str = Form(None),
    price: float = Form(...),
    stock: int = Form(...),

    # Multiple category slugs
    category_slugs: list[str] = Form(...),

    is_active: bool = Form(True),
    image: UploadFile | None = File(None),

    db: Session = Depends(get_db),
    current_user=Depends(admin_required),
):
    # --------------------------------------------------------
    # Find categories
    # --------------------------------------------------------

    categories = (
        db.query(Category)
        .filter(Category.slug.in_(category_slugs))
        .all()
    )

    if len(categories) != len(category_slugs):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="One or more categories not found",
        )

    # --------------------------------------------------------
    # Check duplicate product name
    # --------------------------------------------------------

    existing_product = (
        db.query(Product)
        .filter(Product.name == name)
        .first()
    )

    if existing_product:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Product with this name already exists",
        )

    # --------------------------------------------------------
    # Generate product slug
    # --------------------------------------------------------

    slug = generate_slug(name)

    # --------------------------------------------------------
    # Check duplicate slug
    # --------------------------------------------------------

    existing_slug = (
        db.query(Product)
        .filter(Product.slug == slug)
        .first()
    )

    if existing_slug:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Product with this slug already exists",
        )

    # --------------------------------------------------------
    # Upload image
    # --------------------------------------------------------

    image_url = None

    if image:
        image_url = await upload_product_image(image)

    # --------------------------------------------------------
    # Create product
    # --------------------------------------------------------

    product = Product(
        name=name,
        slug=slug,
        description=description,
        price=price,
        stock=stock,
        image=image_url,
        is_active=is_active,

        # Many-to-many relationship
        categories=categories,
    )

    db.add(product)
    db.commit()
    db.refresh(product)

    return product


# ============================================================
# ADMIN - GET ALL PRODUCTS
# Shows active + inactive products
# ============================================================

@router.get(
    "/admin/products",
    response_model=list[ProductResponse],
)
def get_all_products_admin(
    db: Session = Depends(get_db),
    current_user=Depends(admin_required),
):
    products = (
        db.query(Product)
        .all()
    )

    return products


# ============================================================
# CUSTOMER - GET ACTIVE PRODUCTS
# ============================================================

@router.get(
    "/",
    response_model=list[ProductResponse],
)
def get_products(
    db: Session = Depends(get_db),
):
    products = (
        db.query(Product)
        .filter(Product.is_active == True)
        .all()
    )

    return products


# ============================================================
# CUSTOMER - GET PRODUCTS BY CATEGORY
# Example: GET /shoes
# ============================================================

@router.get(
    "/{category_slug}",
    response_model=list[ProductResponse],
)
def get_products_by_category(
    category_slug: str,
    db: Session = Depends(get_db),
):
    # --------------------------------------------------------
    # Find category
    # --------------------------------------------------------

    category = (
        db.query(Category)
        .filter(Category.slug == category_slug)
        .first()
    )

    if not category:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Category not found",
        )

    # --------------------------------------------------------
    # Get active products belonging to this category
    # --------------------------------------------------------

    products = (
        db.query(Product)
        .filter(
            Product.categories.any(
                Category.id == category.id
            ),
            Product.is_active == True,
        )
        .all()
    )

    return products


# ============================================================
# CUSTOMER - GET SINGLE PRODUCT
# Example:
# GET /shoes/nike-air-max
# ============================================================

@router.get(
    "/{category_slug}/{product_slug}",
    response_model=ProductResponse,
)
def get_product(
    category_slug: str,
    product_slug: str,
    db: Session = Depends(get_db),
):
    # --------------------------------------------------------
    # Find category
    # --------------------------------------------------------

    category = (
        db.query(Category)
        .filter(Category.slug == category_slug)
        .first()
    )

    if not category:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Category not found",
        )

    # --------------------------------------------------------
    # Find product inside category
    # --------------------------------------------------------

    product = (
        db.query(Product)
        .filter(
            Product.slug == product_slug,

            Product.categories.any(
                Category.id == category.id
            ),

            Product.is_active == True,
        )
        .first()
    )

    if not product:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Product not found in this category",
        )

    return product


# ============================================================
# UPDATE PRODUCT
# Example:
# PUT /shoes/nike-air-max
# ============================================================

@router.put(
    "/{category_slug}/{product_slug}",
    response_model=ProductResponse,
)
async def update_product(
    category_slug: str,
    product_slug: str,

    name: str | None = Form(None),
    description: str | None = Form(None),
    price: float | None = Form(None),
    stock: int | None = Form(None),
    is_active: bool | None = Form(None),

    # Replace product categories
    category_slugs: list[str] | None = Form(None),

    image: UploadFile | None = File(None),

    db: Session = Depends(get_db),
    current_user=Depends(admin_required),
):
    # --------------------------------------------------------
    # Find current category
    # --------------------------------------------------------

    category = (
        db.query(Category)
        .filter(Category.slug == category_slug)
        .first()
    )

    if not category:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Category not found",
        )

    # --------------------------------------------------------
    # Find product inside current category
    # --------------------------------------------------------

    product = (
        db.query(Product)
        .filter(
            Product.slug == product_slug,

            Product.categories.any(
                Category.id == category.id
            ),
        )
        .first()
    )

    if not product:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Product not found in this category",
        )

    # --------------------------------------------------------
    # Update name + slug
    # --------------------------------------------------------

    if name is not None:

        new_slug = generate_slug(name)

        existing_product = (
            db.query(Product)
            .filter(
                Product.slug == new_slug,
                Product.id != product.id,
            )
            .first()
        )

        if existing_product:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Another product already uses this name",
            )

        product.name = name
        product.slug = new_slug

    # --------------------------------------------------------
    # Update description
    # --------------------------------------------------------

    if description is not None:
        product.description = description

    # --------------------------------------------------------
    # Update price
    # --------------------------------------------------------

    if price is not None:
        product.price = price

    # --------------------------------------------------------
    # Update stock
    # --------------------------------------------------------

    if stock is not None:
        product.stock = stock

    # --------------------------------------------------------
    # Update active status
    # --------------------------------------------------------

    if is_active is not None:
        product.is_active = is_active

    # --------------------------------------------------------
    # Update categories
    # --------------------------------------------------------

    if category_slugs is not None:

        categories = (
            db.query(Category)
            .filter(Category.slug.in_(category_slugs))
            .all()
        )

        if len(categories) != len(category_slugs):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="One or more categories not found",
            )

        # Replace existing categories
        product.categories = categories

    # --------------------------------------------------------
    # Update image
    # --------------------------------------------------------

    if image:
        product.image = await upload_product_image(image)

    db.commit()
    db.refresh(product)

    return product


# ============================================================
# DELETE PRODUCT
# Example:
# DELETE /shoes/nike-air-max
# ============================================================

@router.delete(
    "/{category_slug}/{product_slug}",
    status_code=status.HTTP_200_OK,
)
def delete_product(
    category_slug: str,
    product_slug: str,

    db: Session = Depends(get_db),
    current_user=Depends(admin_required),
):
    # --------------------------------------------------------
    # Find category
    # --------------------------------------------------------

    category = (
        db.query(Category)
        .filter(Category.slug == category_slug)
        .first()
    )

    if not category:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Category not found",
        )

    # --------------------------------------------------------
    # Find product
    # --------------------------------------------------------

    product = (
        db.query(Product)
        .filter(
            Product.slug == product_slug,

            Product.categories.any(
                Category.id == category.id
            ),
        )
        .first()
    )

    if not product:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Product not found in this category",
        )

    # --------------------------------------------------------
    # Soft delete
    # --------------------------------------------------------

    product.is_active = False

    db.commit()

    return {
        "message": "Product deleted successfully"
    }

