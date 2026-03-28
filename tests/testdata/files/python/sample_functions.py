"""Sample Python functions for testing language detection and parsing."""

def simple_function(a, b):
    """A simple function that adds two numbers."""
    return a + b


def complex_function(data: list[str], filter_func: callable = None) -> dict[str, int]:
    """
    A more complex function with type hints and default parameters.
    
    Args:
        data: List of strings to process
        filter_func: Optional function to filter items
        
    Returns:
        Dictionary with word counts
    """
    result = {}
    for item in data:
        if filter_func is None or filter_func(item):
            result[item] = result.get(item, 0) + 1
    return result


class SampleClass:
    """A sample class for testing class parsing."""
    
    def __init__(self, name: str):
        self.name = name
        self._private_var = "private"
    
    @property
    def display_name(self) -> str:
        """A property method."""
        return f"Sample: {self.name}"
    
    def method_with_args(self, *args, **kwargs):
        """Method with variable arguments."""
        return args, kwargs
    
    @staticmethod
    def static_method():
        """A static method."""
        return "static"


def decorator_function(func):
    """A sample decorator."""
    def wrapper(*args, **kwargs):
        print(f"Calling {func.__name__}")
        return func(*args, **kwargs)
    return wrapper


@decorator_function
def decorated_function():
    """A function with a decorator."""
    return "decorated"


async def async_function():
    """An async function for testing."""
    return "async result"


def function_with_imports():
    """Function that demonstrates import usage."""
    import json
    from pathlib import Path
    from collections import defaultdict
    
    data = {"key": "value"}
    path = Path("/tmp/test")
    counts = defaultdict(int)
    
    return json.dumps(data), path, counts
