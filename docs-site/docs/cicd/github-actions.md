# GitHub Actions Fleet Indexer

The GitHub Actions workflow (`github-batho.yaml`) automatically indexes your repository on every push and pull request to `main`, using an incremental patching strategy to keep CI cycles fast.

## Workflow

```mermaid
flowchart TD
    A["Push/PR to main"] --> B["actions/checkout@v7"]
    B --> C["Setup Python 3.12"]
    C --> D["pip install batho"]
    D --> E["Download previous artifact_<repo>.batho"]
    E --> F{"Artifact exists?"}
    F -- Yes --> G["batho load --root . artifact_*.batho --force"]
    G --> H["batho patch --root . --verbose"]
    F -- No --> I["batho build --root . --full --verbose"]
    H --> J["batho export --root . --output artifact_<repo>.batho"]
    I --> J
    J --> K["Upload artifact_<repo>.batho"]
    K --> L["Retain 90 days"]
```

## Full Workflow YAML

Copy the following into `.github/workflows/github-batho.yaml`:

```yaml
name: Batho Fleet Indexer

on:
  push:
    branches:
      - main
  pull_request:
    branches:
      - main

concurrency:
  group: batho-fleet-${{ github.workflow }}-${{ github.ref }}
  cancel-in-progress: true

jobs:
  update-code-graph:
    runs-on: ubuntu-latest
    timeout-minutes: 30
    permissions:
      actions: read    # Required to download previous artifacts
      contents: read   # Required to checkout code

    env:
      BATHO_ARTIFACT: artifact_${{ github.event.repository.name }}.batho

    steps:
      - name: Checkout Code
        uses: actions/checkout@v7

      - name: Setup Python
        uses: actions/setup-python@v6
        with:
          python-version: '3.12'

      - name: Install Batho
        run: pip install batho

      - name: Download Previous Batho Artifact
        # Fetches the artifact from the last successful run on this branch
        uses: dawidd6/action-download-artifact@v21
        continue-on-error: true # Will fail on the very first run, which is expected
        with:
          github_token: ${{ secrets.GITHUB_TOKEN }}
          workflow: github-batho.yaml # MUST match the filename of this yaml file
          branch: ${{ github.ref_name }}
          name: ${{ env.BATHO_ARTIFACT }}
          path: .

      - name: Run Batho (Patch or Build)
        run: |
          # Batho stores the code graph as Arrow IPC files packed into artifact_<repo>.batho
          if ls artifact_*.batho 1> /dev/null 2>&1; then
            echo "✅ Found existing Batho artifact. Running incremental patch..."
            batho load --root . artifact_*.batho --force
            batho patch --root . --verbose
          else
            echo "⚠️ No existing artifact found. Running full build..."
            batho build --root . --full --verbose
          fi
          # Export the updated .batho/ bundle into a transport artifact
          batho export --root . --output "${BATHO_ARTIFACT}"

      - name: Upload Updated Artifact
        uses: actions/upload-artifact@v7
        with:
          name: ${{ env.BATHO_ARTIFACT }}
          path: ${{ env.BATHO_ARTIFACT }}
          retention-days: 90
```

## Key Configuration

| Key | Value | Purpose |
|---|---|---|
| **Triggers** | `push` + `pull_request` to `main` | Run on every commit and PR |
| **Concurrency** | `cancel-in-progress: true` | Prevent redundant overlapping runs |
| **Timeout** | `30 minutes` | Fail fast if something hangs |
| **Runner** | `ubuntu-latest` | Standard GitHub-hosted runner |
| **Permissions** | `actions: read`, `contents: read` | Minimal permissions principle |
| **Install** | `pip install batho` | Pulls latest stable from PyPI |
| **Artifact name** | `artifact_<repo>.batho` | Repo-based name, consistent across runs for reliable downloads |
| **Retention** | `90 days` | Long enough for agent access |

## First-Run Behavior

On the very first run there is no previous artifact, so the download step fails gracefully (`continue-on-error: true`) and the workflow falls through to a full `batho build --full`.

## AI Agent Access

Agents can download and restore the graph:

```bash
# Download latest artifact from main branch
gh api \
  /repos/{owner}/{repo}/actions/artifacts \
  --jq '.artifacts[] | select(.name|startswith("artifact_") and endswith(".batho")) | .id' \
  | xargs -I {} gh api \
  /repos/{owner}/{repo}/actions/artifacts/{}/zip \
  --output batho-artifact.zip
unzip batho-artifact.zip

# Restore the Arrow IPC graph store
batho load --root . artifact_*.batho
```

## Troubleshooting

| Issue | Cause | Resolution |
|---|---|---|
| Artifact download fails | First run (no previous artifact) | Expected — workflow continues with full build |
| Workflow filename mismatch | `workflow` parameter doesn't match actual filename | Ensure `workflow: github-batho.yaml` matches your file |
| `batho load` fails | Schema version mismatch | Delete artifact to trigger full rebuild |
| Build timeout | Very large repository | Increase `timeout-minutes` or split into multiple jobs |
