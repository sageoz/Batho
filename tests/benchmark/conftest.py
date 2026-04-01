"""
Pytest configuration for determinism benchmarks.
"""
import pytest
from pathlib import Path

def pytest_configure(config):
    config.addinivalue_line("markers", "quick: mark test as a 10-run smoke test")
    config.addinivalue_line("markers", "full: mark test as a 1000-run full determinism suite")

@pytest.fixture
def fixture_path():
    def _get_path(language: str) -> Path:
        p = Path(__file__).parent / "fixtures" / language
        # If the directory doesn't exist or is empty (uninitialized submodule)
        if not p.exists() or not any(Path(p).iterdir()):
            pytest.skip(f"Fixture for {language} not initialized. Run git submodule update.")
        return p
    return _get_path
