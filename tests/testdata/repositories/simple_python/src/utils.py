"""Utility helpers that import from calculator."""

from calculator import add, Calculator


def double(x: int) -> int:
    """Double a value using add."""
    return add(x, x)


def create_calculator() -> Calculator:
    """Factory function for Calculator."""
    return Calculator()


PI = 3.14159
