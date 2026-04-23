# cicd/ — parked GitHub CI/CD assets

This folder stages the Batho GitHub Actions integration **without activating
it**. Nothing here runs until the files are moved to their canonical GitHub
locations. See `docs/github-actions.md` for the full design.

## Contents

- `action.yml` — composite GitHub Action (`Batho Index`). When activated,
  this file must live at the **repo root** so GitHub can resolve
  `uses: sageoz/batho@<ref>`.
- `batho-index.yml` — reusable workflow. When activated, it must live at
  `.github/workflows/batho-index.yml` so consumers can call it via
  `uses: sageoz/batho/.github/workflows/batho-index.yml@<ref>`.
- `starter-batho.yml` — copy-pasteable starter workflow for consumer repos
  (lands in `<consumer>/.github/workflows/batho.yml`). This file stays in
  the Batho repo as documentation only.

## Activation checklist (when ready)

1. `git mv cicd/action.yml action.yml`
2. `git mv cicd/batho-index.yml .github/workflows/batho-index.yml`
3. Move `starter-batho.yml` back under `docs/ci/` (or wherever docs live)
   and update the link in `README.md` / `docs/github-actions.md`.
4. Revert the script-path tweak in `action.yml`:
   `${{ github.action_path }}/../scripts/ci/render_summary.py`
   → `${{ github.action_path }}/scripts/ci/render_summary.py`
   and the install line:
   `uv pip install "${ACTION_PATH}/.."`
   → `uv pip install "${ACTION_PATH}"`
5. Tag a release (`v1` moving tag) and smoke-test from a scratch repo.

## Why parked?

Activating the composite action at the repo root commits Batho to a public
Actions contract (inputs, outputs, versioning). We're holding off until we
are ready to publish, tag, and support `sageoz/batho@v1` for end users.
