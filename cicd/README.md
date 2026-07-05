# cicd/ — Batho CI/CD Assets

This directory contains production-ready CI/CD integrations for Batho v1.2.0. Files are kept here for reference and packaging; the canonical activation paths are documented below.

## Contents

| File | Purpose |
|------|---------|
| `action.yml` | Composite GitHub Action (`Batho Index`). When activated, move to **repo root** so GitHub can resolve `uses: sageoz/batho@<ref>`. |
| `batho-index.yml` | Reusable workflow. When activated, move to `.github/workflows/batho-index.yml` so consumers can call it via `uses: sageoz/batho/.github/workflows/batho-index.yml@<ref>`. |
| `starter-batho.yml` | Copy-pasteable starter workflow template for downstream repos (place in `<consumer>/.github/workflows/batho.yml`). |
| `github-batho.yaml` | GitHub Actions fleet indexer — automated code graph indexing on every push/PR. |
| `gitlab-batho.yaml` | GitLab CI fleet indexer — same incremental patching strategy for GitLab. |

---

## Downstream Repository Integration

Consumer repositories can integrate Batho to automatically build and store code indexes:

1. Copy `cicd/starter-batho.yml` into your repository as `.github/workflows/batho.yml`.
2. Commit and push to your main branch.
3. On every push and pull request, the workflow builds a full index and exports a transport ZIP package containing:
   - BSG representation map
   - Code graph
   - Metadata and metrics
4. Access the uploaded ZIP package in your run's **Artifacts** panel under the name `batho-index`.

---

## Activation (For Batho Repo Maintainers)

To make the composite action and reusable workflow resolvable by downstream repos, activate them by moving to their canonical locations:

```bash
# Move composite action to repo root
git mv cicd/action.yml action.yml

# Move reusable workflow to the workflow folder
git mv cicd/batho-index.yml .github/workflows/batho-index.yml
```

After moving, update paths in `action.yml` to remove the parked subdirectory lookup:

- In the **Install Batho** step, change:
  ```
  uv pip install --python "${UV_PROJECT_ENVIRONMENT}" "${ACTION_PATH}/.."
  ```
  to:
  ```
  uv pip install --python "${UV_PROJECT_ENVIRONMENT}" "${ACTION_PATH}"
  ```

Tag a release (e.g. `v1.2.0`) and smoke test from a scratch repository.
