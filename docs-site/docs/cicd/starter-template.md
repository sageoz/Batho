# Starter Template

The starter template (`starter-batho.yml`) is a ready-to-copy workflow for consumer repositories. It demonstrates both the composite action and the reusable workflow approaches.

## Quick Start

1. Copy `cicd/starter-batho.yml` from the Batho repository.
2. Paste it into your repository as `.github/workflows/batho.yml`.
3. Commit and push to `main`.
4. The workflow runs on every push and PR to `main`, building and exporting a Batho index artifact.

## Full Template

```yaml
# Starter GitHub Actions workflow for running Batho on every push / PR.
#
# Copy this file into your repo as `.github/workflows/batho.yml`.
# Two equivalent flavours are shown: (A) composite action (most flexible),
# (B) reusable workflow (one-liner).
#
# v1.3.1 indexes the repo using "batho build --root ." and exports the transport
# ZIP package (artifact_<dir>.batho) as a workflow artifact. It does NOT fail your build.

name: Batho

on:
  push:
    branches: [main]
  pull_request:
    branches: [main]

concurrency:
  group: batho-${{ github.workflow }}-${{ github.ref }}
  cancel-in-progress: true

permissions:
  contents: read

jobs:
  # --- Flavour A: composite action ---------------------------------------
  batho-index:
    name: Batho Index (composite)
    runs-on: ubuntu-latest
    steps:
      - name: Checkout
        uses: actions/checkout@v7
        with:
          fetch-depth: 0

      - name: Run Batho
        uses: sageoz/batho@v1.3.1
        with:
          root: "."
          python-version: "3.12"
          # Leave `batho-ref` empty to install Batho from the action's own checkout.
          # Or set batho-ref to "pypi" to install from PyPI, or pin a git ref:
          #   batho-ref: "v1.3.1"
          batho-ref: ""
          artifact-name: batho-index
          artifact-retention-days: "7"

  # --- Flavour B: reusable workflow (one-liner) --------------------------
  # Uncomment to use instead of Flavour A.
  #
  # batho-index-reusable:
  #   uses: sageoz/batho/.github/workflows/batho-index.yml@v1.3.1
  #   with:
  #     root: "."
```

## Flavour A vs Flavour B

| Aspect | Composite Action (A) | Reusable Workflow (B) |
|---|---|---|
| **Steps visible** | Yes — each step appears in your run log | No — encapsulated in the reusable workflow |
| **Configurability** | All inputs exposed directly | All inputs exposed via `with:` |
| **Maintenance** | You control the call site | Batho maintainers update the reusable workflow |
| **Best for** | Teams that want visibility | Teams that want minimal boilerplate |

## Configuration Options

### Install Source

```yaml
# From PyPI (recommended for most users)
batho-ref: "pypi"

# From a specific git tag
batho-ref: "v1.3.1"

# From the action's own checkout (for testing or offline)
batho-ref: ""
```

### Artifact Retention

```yaml
# Short retention for small repos
artifact-retention-days: "3"

# Long retention for frequently accessed repos
artifact-retention-days: "30"
```

### Runner

The composite action runs on `ubuntu-latest` by default. The reusable workflow lets you specify:

```yaml
with:
  runs-on: "ubuntu-latest"
```

## What Happens After Push?

1. The workflow checks out your repository with full history (`fetch-depth: 0`).
2. It installs Batho into an isolated uv-managed virtual environment.
3. It builds a full index of your repository (`batho build --root . --full`).
4. It exports the index into a transport ZIP (`artifact_<dirname>.batho`).
5. The ZIP is uploaded as a workflow artifact named `batho-index`.
6. You can find it under **Actions → your run → Artifacts**.

## Next Steps

- **[Composite Action](/docs/cicd/composite-action)** — Deep dive into all available inputs and outputs
- **[Reusable Workflow](/docs/cicd/reusable-workflow)** — One-liner integration reference
