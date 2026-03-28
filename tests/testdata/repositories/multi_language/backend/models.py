"""Data models for the backend."""


class User:
    """User model."""

    def __init__(self, name: str, email: str):
        self.name = name
        self.email = email

    def to_dict(self) -> dict:
        return {"name": self.name, "email": self.email}


class Product:
    """Product model inheriting nothing special."""

    def __init__(self, title: str, price: float):
        self.title = title
        self.price = price


class AdminUser(User):
    """Admin user extends User."""

    def __init__(self, name: str, email: str, role: str = "admin"):
        super().__init__(name, email)
        self.role = role
