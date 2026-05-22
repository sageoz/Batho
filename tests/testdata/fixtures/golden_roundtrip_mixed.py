# Mixed content: comments, imports, code

# Import block
import json
import os
from typing import Any, Optional

# Constants
DEFAULT_TIMEOUT = 30
MAX_RETRIES = 3

# Core function
def fetch_data(url: str, timeout: int = DEFAULT_TIMEOUT) -> Optional[dict[str, Any]]:
    """Fetch data from a URL.

    Args:
        url: The endpoint.
        timeout: Request timeout.

    Returns:
        Parsed JSON or None.
    """
    import urllib.request
    import urllib.error

    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, json.JSONDecodeError) as exc:
        print(f"Error: {exc}")
        return None


# Entry point
if __name__ == "__main__":
    result = fetch_data("https://example.com/api")
    print(result)