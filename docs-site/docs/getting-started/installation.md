---
sidebar_position: 2
title: "Installation"
description: "Install Batho via pip, uv, pipx, or from source"
---

# Installation

## PyPI Install

```bash
pip install batho          # pip (or: python -m pip install batho / python3 -m pip install batho)
uv pip install batho       # uv (faster alternative)
pipx install batho         # pipx (isolated global CLI install)
pip install -e .           # development (editable)
```

**PyPI:** https://pypi.org/project/batho/

---

## Developer Setup (uv)

Use this section when you want to contribute to Batho locally, run tests, and verify the CLI from source.

### 1. Clone the repository

```bash
git clone https://github.com/sageoz/batho.git
cd batho
```

### 2. Install project dependencies

```bash
uv sync --all-groups --all-extras
```

This creates and syncs the project environment with runtime, test, and dev dependencies.

### 3. Run tests

```bash
# Full suite
uv run pytest

# Optional: focused checks while iterating
uv run pytest tests/core/test_config.py -q
uv run pytest tests/utils/test_logging.py -q
```

### 4. Run the CLI directly from local source

```bash
uv run python -m batho_cli --help
uv run python -m batho_cli build --root .
```

### 5. Reinstall the global batho command

```bash
uv tool install --reinstall .
hash -r
batho build --root .
```

### 6. Quick troubleshooting

If behavior differs between local and global runs, compare both paths:

```bash
uv run python -m batho_cli build --root .
batho build --root .
```

If they differ, reinstall the tool again:

```bash
uv tool install --reinstall .
hash -r
```
