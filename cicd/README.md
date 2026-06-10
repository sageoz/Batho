# cicd/ — Parked GitHub CI/CD Assets for Batho

This directory stages the Batho GitHub Actions integration **without activating it** at the repository root level. Nothing here runs in this repo until the files are moved to their canonical GitHub locations.

## Contents

- `action.yml` — composite GitHub Action (`Batho Index`). When activated, this file must live at the **repo root** so GitHub can resolve `uses: sageoz/batho@<ref>`.
- `batho-index.yml` — reusable workflow. When activated, it must live at `.github/workflows/batho-index.yml` so consumer repositories can call it via `uses: sageoz/batho/.github/workflows/batho-index.yml@<ref>`.
- `starter-batho.yml` — copy-pasteable starter workflow template for downstream repos (lands in `<consumer>/.github/workflows/batho.yml`).

---

## Downstream Repository Integration

Downstream/consumer repositories can easily integrate Batho to automatically build and store code indexes for semantic search or analysis:

1. Copy `cicd/starter-batho.yml` from this repository to your repository as `.github/workflows/batho.yml`.
2. Commit and push the file to your main branch.
3. On every push and pull request, the workflow will build a full index and export a transport ZIP package containing:
   - BSG representation map
   - Code graph
   - Metadata and metrics
4. Access the uploaded ZIP package in your run's **Artifacts** panel under the name `batho-index`.

---

## Activation Checklist (For Batho Repo Maintainers)

When Batho is ready for public consumption and version pinning (e.g. tagging `v1.1.0`), activate the CI/CD integration using the following steps:

1. Move the composite action to the repository root:
   ```bash
   git mv cicd/action.yml action.yml
   ```
2. Move the reusable workflow to the workflow folder:
   ```bash
   git mv cicd/batho-index.yml .github/workflows/batho-index.yml
   ```
3. Update paths in `action.yml` to remove the parked subdirectory lookup:
   - In the "Install Batho" step, change:
     `uv pip install --python "${UV_PROJECT_ENVIRONMENT}" "${ACTION_PATH}/.."`
     to:
     `uv pip install --python "${UV_PROJECT_ENVIRONMENT}" "${ACTION_PATH}"`
4. Tag a release (e.g. `v1.1.0`) and smoke test the action from a scratch repository.
