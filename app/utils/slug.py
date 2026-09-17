# ============================================================
# Helper Function
# ============================================================
import re

def generate_slug(name: str) -> str:
    """
    Generate a URL-friendly slug.

    Example:
        Men's Fashion -> men-s-fashion
        Mobile Phones -> mobile-phones
    """

    slug = name.lower().strip()

    slug = re.sub(
        r"[^a-z0-9]+",
        "-",
        slug,
    )

    slug = slug.strip("-")

    return slug