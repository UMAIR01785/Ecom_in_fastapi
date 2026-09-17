import cloudinary
import cloudinary.uploader

from app.config import settings


cloudinary.config(
    cloud_name=settings.cloudinary_cloud_name,
    api_key=settings.cloudinary_api_key,
    api_secret=settings.cloudinary_api_secret,
)


def upload_profile_image(file_data: bytes):
    result = cloudinary.uploader.upload(
        file_data,
        folder="ecommerce/profile_images"
    )

    return {
        "url": result["secure_url"],
        "public_id": result["public_id"],
    }
def delete_profile_image(public_id: str):
    result = cloudinary.uploader.destroy(public_id)

    return result


import cloudinary.uploader
from fastapi import UploadFile


async def upload_category_image(
    file: UploadFile,
) -> str:

    contents = await file.read()

    result = cloudinary.uploader.upload(
        contents,
        folder="ecommerce/categories",
    )

    return result["secure_url"]


async def upload_product_image(
    file: UploadFile,
) -> str:

    contents = await file.read()

    result = cloudinary.uploader.upload(
        contents,
        folder="ecommerce/Products",
    )

    return result["secure_url"]
    