import cloudinary
import cloudinary.uploader
from cloudinary.utils import cloudinary_url

from app.config import settings


def main() -> None:
    """
    Simple Cloudinary connectivity test.
    Uses credentials from app.config.Settings (which loads .env).
    """

    if not (
        settings.cloudinary_cloud_name
        and settings.cloudinary_api_key
        and settings.cloudinary_api_secret
    ):
        print(
            "Missing Cloudinary settings. Please set cloudinary_cloud_name, "
            "cloudinary_api_key, cloudinary_api_secret in your .env."
        )
        return

    cloudinary.config(
        cloud_name=settings.cloudinary_cloud_name,
        api_key=settings.cloudinary_api_key,
        api_secret=settings.cloudinary_api_secret,
        secure=True,
    )

    print(f"Using Cloudinary cloud_name={settings.cloudinary_cloud_name}")

    # Upload a known demo image by URL (as in Cloudinary docs)
    demo_url = "https://res.cloudinary.com/demo/image/upload/getting-started/shoes.jpg"
    print(f"Uploading demo image from {demo_url} ...")

    upload_result = cloudinary.uploader.upload(
        demo_url,
        public_id="trustbond_demo_shoes",
    )
    secure_url = upload_result.get("secure_url") or upload_result.get("url")
    print(f"Uploaded demo image URL: {secure_url}")

    # Show an optimized URL
    optimize_url, _ = cloudinary_url("trustbond_demo_shoes", fetch_format="auto", quality="auto")
    print(f"Optimized URL: {optimize_url}")


if __name__ == "__main__":
    main()

