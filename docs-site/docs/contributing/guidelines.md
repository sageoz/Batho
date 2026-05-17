---
sidebar_position: 2
title: "Contributing Guidelines"
description: "Code style, PR process, and testing requirements"
---

# Contributing Guidelines

## Code Style

- Follow PEP 8 conventions
- Use `ruff` for linting and formatting
- Type hints are encouraged for public APIs
- Docstrings use Google style

## Pull Request Process

1. Fork the repository and create a feature branch
2. Make your changes with clear, focused commits
3. Add or update tests for any new functionality
4. Ensure the full test suite passes: `uv run pytest`
5. Update relevant documentation if needed
6. Submit a PR with a clear description of changes

## Testing Requirements

- All new features must include tests
- Aim to maintain or improve overall coverage
- Use `pytest` fixtures for shared test setup
- Mock external dependencies (network, filesystem) appropriately

## Commit Messages

Use conventional commits style when possible:

- `feat:` new feature
- `fix:` bug fix
- `docs:` documentation changes
- `refactor:` code refactoring
- `test:` test additions or updates
- `chore:` maintenance tasks
