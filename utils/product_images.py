import logging
import os
import secrets

from flask import current_app


logger = logging.getLogger(__name__)
MAX_PRODUCT_IMAGE_SIZE = 5 * 1024 * 1024
PRODUCT_IMAGE_FOLDER = os.path.join("uploads", "products")
MAX_PROFILE_IMAGE_SIZE = 5 * 1024 * 1024
PROFILE_IMAGE_FOLDER = os.path.join("uploads", "profiles")
IMAGE_SIGNATURES = (
    (".jpg", lambda header: header.startswith(b"\xff\xd8\xff")),
    (".png", lambda header: header.startswith(b"\x89PNG\r\n\x1a\n")),
    (
        ".webp",
        lambda header: (
            len(header) >= 12
            and header.startswith(b"RIFF")
            and header[8:12] == b"WEBP"
        )
    )
)


def _save_image(upload, image_folder, max_size, size_error):
    if not upload or not upload.filename:
        return None

    upload.seek(0, os.SEEK_END)
    file_size = upload.tell()
    upload.seek(0)

    if file_size <= 0:
        raise ValueError("The selected product image is empty.")

    if file_size > max_size:
        raise ValueError(size_error)

    header = upload.read(12)
    upload.seek(0)

    extension = next(
        (
            suffix
            for suffix, is_valid in IMAGE_SIGNATURES
            if is_valid(header)
        ),
        None
    )

    if extension is None:
        raise ValueError("Upload a valid JPG, PNG, or WebP image.")

    folder = os.path.join(
        current_app.static_folder,
        image_folder
    )
    os.makedirs(folder, exist_ok=True)

    filename = f"{secrets.token_hex(16)}{extension}"
    full_path = os.path.join(folder, filename)
    relative_path = os.path.join(
        image_folder,
        filename
    ).replace(os.sep, "/")

    try:
        upload.save(full_path)
    except OSError:
        logger.exception("Unable to save product image.")
        raise

    return relative_path


def save_product_image(upload):
    return _save_image(
        upload,
        PRODUCT_IMAGE_FOLDER,
        MAX_PRODUCT_IMAGE_SIZE,
        "Product images must not exceed 5 MB."
    )


def save_profile_image(upload):
    return _save_image(
        upload,
        PROFILE_IMAGE_FOLDER,
        MAX_PROFILE_IMAGE_SIZE,
        "Profile photos must not exceed 5 MB."
    )


def _delete_image(relative_path, image_folder, label):
    if not relative_path:
        return

    normalized_path = os.path.normpath(relative_path)
    expected_folder = os.path.realpath(
        os.path.join(
            current_app.static_folder,
            image_folder
        )
    )
    full_path = os.path.realpath(
        os.path.join(current_app.static_folder, normalized_path)
    )

    try:
        if os.path.commonpath((expected_folder, full_path)) != expected_folder:
            logger.warning("Skipped deletion of an invalid %s path.", label)
            return
    except ValueError:
        logger.warning("Skipped deletion of an invalid %s path.", label)
        return

    if not os.path.isfile(full_path):
        return

    try:
        os.remove(full_path)
    except OSError:
        logger.exception("Unable to remove old %s.", label)


def delete_product_image(relative_path):
    _delete_image(relative_path, PRODUCT_IMAGE_FOLDER, "product image")


def delete_profile_image(relative_path):
    _delete_image(relative_path, PROFILE_IMAGE_FOLDER, "profile photo")
