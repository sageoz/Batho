#!/usr/bin/env bash
# =============================================================================
# build_and_deploy_containers.sh
# Build and verify Batho LSP containers in Podman.
#
# Usage:
#   bash scripts/build_and_deploy_containers.sh              # Build all
#   bash scripts/build_and_deploy_containers.sh --language python  # Build one
# =============================================================================
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

LANGUAGE=""
BUILDER="podman"

# ─── Helpers ──────────────────────────────────────────────────────────────────
get_version() {
  case "$1" in
    python)     echo "1.1.350" ;;
    typescript) echo "4.3.3" ;;
    go)         echo "0.15.3" ;;
    rust)       echo "2024-02-12" ;;
    java)       echo "1.31.0" ;;
    cpp)        echo "17.0.3" ;;
    *)          echo "unknown" ;;
  esac
}

get_build_args() {
  case "$1" in
    python)     echo "--build-arg PYRIGHT_VERSION=1.1.350" ;;
    typescript) echo "--build-arg TSSERVER_VERSION=4.3.3" ;;
    go)         echo "--build-arg GOPLS_VERSION=0.15.3" ;;
    rust)       echo "--build-arg RUST_ANALYZER_DATE=2024-02-12" ;;
    java)       echo "--build-arg JDTLS_VERSION=1.31.0" ;;
    cpp)        echo "--build-arg CLANGD_VERSION=17.0.3" ;;
    *)          echo "" ;;
  esac
}

check_podman() {
  echo "→ Checking Podman machine..."
  if ! $BUILDER machine list 2>/dev/null | grep -qE "(running|Currently running)"; then
    echo "  Podman machine is not running. Starting it..."
    $BUILDER machine start
  else
    echo "  ✅ Podman machine is running"
  fi
}

build_language() {
  local lang="$1"
  local version
  version="$(get_version "$lang")"
  local image_tag="batho-lsp/${lang}:${version}"
  local containerfile="containers/${lang}/Containerfile"
  local args
  args="$(get_build_args "$lang")"

  if [[ ! -f "$containerfile" ]]; then
    echo "  ⚠️  Containerfile not found: $containerfile (skipping $lang)"
    return 0
  fi

  echo ""
  echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
  echo "  Building: $image_tag"
  echo "  File:     $containerfile"
  echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

  # shellcheck disable=SC2086
  $BUILDER build \
    -t "$image_tag" \
    -f "$containerfile" \
    $args \
    .

  if $BUILDER images --format "{{.Repository}}:{{.Tag}}" 2>/dev/null | grep -qF "${image_tag}"; then
    echo "  ✅ ${image_tag} — built successfully"
  else
    echo "  ❌ ${image_tag} — image not found after build!"
    exit 1
  fi
}

# ─── Parse args ──────────────────────────────────────────────────────────────
while [[ $# -gt 0 ]]; do
  case "$1" in
    --language) LANGUAGE="$2"; shift 2 ;;
    --builder)  BUILDER="$2";  shift 2 ;;
    *) echo "Unknown arg: $1"; exit 1 ;;
  esac
done

# ─── Main ─────────────────────────────────────────────────────────────────────
echo "============================================="
echo " Batho LSP Container Builder"
echo " Builder: $BUILDER"
echo "============================================="

check_podman

ALL_LANGS="python typescript go rust java cpp"

if [[ -n "$LANGUAGE" ]]; then
  if [[ "$(get_version "$LANGUAGE")" == "unknown" ]]; then
    echo "Unknown language: $LANGUAGE"
    echo "Valid options: $ALL_LANGS"
    exit 1
  fi
  build_language "$LANGUAGE"
else
  for lang in $ALL_LANGS; do
    build_language "$lang"
  done
fi

echo ""
echo "============================================="
echo " Build Summary"
echo "============================================="
$BUILDER images --format "table {{.Repository}}\t{{.Tag}}\t{{.Size}}" 2>/dev/null | grep "batho-lsp" || echo "(no batho-lsp images found)"
echo ""
echo "Done! ✅"
