"""Simple calculator module for testing."""


def add(a: int, b: int) -> int:
    """Add two numbers."""
    return a + b


def subtract(a: int, b: int) -> int:
    """Subtract b from a."""
    return a - b


def multiply(a: int, b: int) -> int:
    """Multiply two numbers."""
    return a * b


def divide(a: float, b: float) -> float:
    """Divide a by b."""
    if b == 0:
        raise ValueError("Cannot divide by zero")
    return a / b


class Calculator:
    """A simple calculator class."""

    def __init__(self):
        self.history: list[tuple[str, float]] = []

    def calculate(self, op: str, a: float, b: float) -> float:
        """Perform an operation and record history."""
        ops = {"add": add, "subtract": subtract, "multiply": multiply, "divide": divide}
        if op not in ops:
            raise ValueError(f"Unknown operation: {op}")
        result = ops[op](a, b)
        self.history.append((op, result))
        return result

    def last_result(self) -> float | None:
        """Return the last result, or None."""
        return self.history[-1][1] if self.history else None
