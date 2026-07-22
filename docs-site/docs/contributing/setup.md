---
sidebar_position: 1
title: "Developer Setup"
description: "Set up your local development environment"
---

# Developer Setup

## Prerequisites

- Python 3.12+
- [uv](https://docs.astral.sh/uv/) (recommended)
- Git

## 1. Clone the repository

```bash
git clone https://github.com/sageoz/batho.git
cd batho
```

## 2. Install dependencies

```bash
uv sync --all-groups --all-extras
```

## 3. Run tests

```bash
# Full suite
uv run pytest

# Optional: focused checks while iterating
uv run pytest tests/core/test_config.py -q
uv run pytest tests/utils/test_logging.py -q
```

## 4. Run the CLI from source

```bash
uv run python -m batho_cli --help
uv run python -m batho_cli build --root .
```

## 5. Reinstall global command

```bash
uv tool install --reinstall .
hash -r
batho build --root .
```

## 6. Troubleshooting

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
