"""Shared fixtures for MCP server tests.

Provides built artifact directories and sample repositories for testing
the Batho MCP tools against real Arrow IPC artifacts.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from batho.orchestrator.build import run_build, BuildOptions


@pytest.fixture(autouse=True)
def _isolate_default_registry(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Redirect the default MCP registry path to a temp file.

    Without this, tests that call create_app()/RepoRegistry() without an
    explicit config_path read the developer's real ~/.batho/mcp-repos.json,
    and _resolve_repo() prefers registry entries over the test's root.
    """
    import batho.mcp.registry as registry_mod

    monkeypatch.setattr(
        registry_mod, "DEFAULT_CONFIG_PATH", tmp_path / "isolated-mcp-repos.json"
    )


@pytest.fixture
def sample_repo(tmp_path: Path) -> Path:
    """Create a minimal Python repository with functions, classes, and relationships.

    Returns the root path of the sample repo.
    """
    root = tmp_path / "sample_repo"
    root.mkdir()

    (root / "main.py").write_text(
        "from utils import helper\n"
        "from models import User\n"
        "\n"
        "def main():\n"
        "    user = User('Alice')\n"
        "    helper(user)\n"
        "    return user\n"
        "\n"
        "class App:\n"
        "    def __init__(self):\n"
        "        self.name = 'MyApp'\n"
        "\n"
        "    def run(self):\n"
        "        return main()\n",
        encoding="utf-8",
    )

    (root / "utils.py").write_text(
        "def helper(obj):\n"
        "    print(obj)\n"
        "    return obj\n"
        "\n"
        "def format_output(data):\n"
        "    return str(data)\n",
        encoding="utf-8",
    )

    (root / "models.py").write_text(
        "class User:\n"
        "    def __init__(self, name):\n"
        "        self.name = name\n"
        "\n"
        "    def get_name(self):\n"
        "        return self.name\n"
        "\n"
        "class Admin(User):\n"
        "    def __init__(self, name, level):\n"
        "        super().__init__(name)\n"
        "        self.level = level\n",
        encoding="utf-8",
    )

    return root


@pytest.fixture
def built_artifact(sample_repo: Path) -> Path:
    """Run `batho build` on the sample repo and return the root path.

    The artifact directory will be at `sample_repo / .batho / artifact`.
    """
    result = run_build(BuildOptions(root=sample_repo, force_full=True))
    assert result.success, f"Build failed: {result.warnings}"
    return sample_repo


@pytest.fixture
def patched_artifact(built_artifact: Path) -> Path:
    """Modify a file and run `batho patch`, returning the root path.

    The artifact will have both a base build and a patch run.
    """
    from batho.orchestrator.patch import run_patch, PatchOptions

    (built_artifact / "utils.py").write_text(
        "def helper(obj):\n"
        "    print(f'Helping: {obj}')\n"
        "    return obj\n"
        "\n"
        "def format_output(data):\n"
        "    return str(data)\n"
        "\n"
        "def new_function():\n"
        "    return 'new'\n",
        encoding="utf-8",
    )

    result = run_patch(PatchOptions(root=built_artifact, verbose=False))
    assert result.success, f"Patch failed: {result.warnings}"
    return built_artifact
