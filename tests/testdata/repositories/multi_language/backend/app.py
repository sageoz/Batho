"""Backend application module."""

from models import User, Product


def get_users() -> list[User]:
    """Return all users."""
    return []


def get_product(product_id: int) -> Product | None:
    """Fetch a product by ID."""
    return None


class AppConfig:
    """Application configuration."""

    DEBUG = True
    DATABASE_URL = "postgresql://localhost/test"
