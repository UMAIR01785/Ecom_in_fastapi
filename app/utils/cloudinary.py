import cloudinary.uploader


def upload_image(file):
    result = cloudinary.uploader.upload(
        file,
        folder="ecommerce"
    )

    return result["secure_url"]