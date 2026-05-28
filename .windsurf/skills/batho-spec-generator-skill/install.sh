#!/bin/bash
#
# spec-generator-skill Installation Script
#
# This script installs the spec-generator-skill to the appropriate location
# based on the detected platform.
#

set -e

SKILL_NAME="spec-generator-skill"
SKILL_DIR="$(cd "$(dirname "$0")" && pwd)"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

log_info() {
    echo -e "${GREEN}[INFO]${NC} $1"
}

log_warn() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

detect_platform() {
    if [ -d "$HOME/.claude/" ]; then
        echo "claude-code"
    elif [ -d "$HOME/.cursor/" ]; then
        echo "cursor-user"
    elif [ -d ".cursor/" ]; then
        echo "cursor-project"
    elif [ -d "$HOME/.codeium/windsurf/" ]; then
        echo "windsurf-user"
    elif [ -d ".windsurf/" ]; then
        echo "windsurf-project"
    elif [ -d ".github/" ]; then
        echo "copilot"
    elif [ -d ".clinerules/" ]; then
        echo "cline"
    elif [ -d "$HOME/.gemini/" ]; then
        echo "gemini-cli"
    elif [ -d ".kiro/" ]; then
        echo "kiro"
    elif [ -d ".trae/" ]; then
        echo "trae"
    elif [ -d "$HOME/.config/goose/" ]; then
        echo "goose"
    elif [ -d "$HOME/.config/opencode/" ]; then
        echo "opencode"
    elif [ -d "$HOME/.agents/skills/" ]; then
        echo "universal"
    else
        echo "unknown"
    fi
}

get_install_path() {
    local platform="$1"
    case "$platform" in
        claude-code)
            echo "$HOME/.claude/skills/$SKILL_NAME"
            ;;
        cursor-user)
            echo "$HOME/.cursor/rules/$SKILL_NAME"
            ;;
        cursor-project)
            echo ".cursor/rules/$SKILL_NAME"
            ;;
        windsurf-user)
            echo "$HOME/.codeium/windsurf/rules/$SKILL_NAME"
            ;;
        windsurf-project)
            echo ".windsurf/workflows/$SKILL_NAME"
            ;;
        copilot)
            echo ".github/skills/$SKILL_NAME"
            ;;
        cline)
            echo ".clinerules/$SKILL_NAME"
            ;;
        gemini-cli)
            echo "$HOME/.gemini/skills/$SKILL_NAME"
            ;;
        kiro)
            echo ".kiro/skills/$SKILL_NAME"
            ;;
        trae)
            echo ".trae/rules/$SKILL_NAME"
            ;;
        goose)
            echo "$HOME/.config/goose/skills/$SKILL_NAME"
            ;;
        opencode)
            echo "$HOME/.config/opencode/skills/$SKILL_NAME"
            ;;
        universal)
            echo "$HOME/.agents/skills/$SKILL_NAME"
            ;;
        *)
            echo ""
            ;;
    esac
}

install_skill() {
    local platform="$1"
    local install_path="$2"

    log_info "Installing $SKILL_NAME for platform: $platform"

    if [ -z "$install_path" ]; then
        log_error "Could not determine install path for platform: $platform"
        return 1
    fi

    # Create parent directory if it doesn't exist
    local parent_dir="$(dirname "$install_path")"
    if [ ! -d "$parent_dir" ]; then
        log_info "Creating directory: $parent_dir"
        mkdir -p "$parent_dir"
    fi

    # Remove existing installation if present
    if [ -e "$install_path" ]; then
        log_warn "Removing existing installation at $install_path"
        rm -rf "$install_path"
    fi

    # Copy skill to install path
    log_info "Copying skill to $install_path"
    cp -R "$SKILL_DIR" "$install_path"

    # Make scripts executable
    if [ -d "$install_path/scripts" ]; then
        chmod +x "$install_path/scripts/"*.py
    fi

    # Make install.sh executable
    chmod +x "$install_path/install.sh"

    log_info "Installation complete!"
    echo ""
    echo "To use the skill, type in your IDE chat:"
    echo "  /spec-generator"
    echo ""
    echo "Example:"
    echo "  /spec-generator Build a user authentication system"
    echo ""

    return 0
}

show_help() {
    echo "Usage: $0 [OPTIONS]"
    echo ""
    echo "Options:"
    echo "  --platform PLATFORM    Force installation to specific platform"
    echo "  --all                  Install to all detected platforms"
    echo "  --dry-run              Show what would be installed without installing"
    echo "  --help                 Show this help message"
    echo ""
    echo "Supported platforms:"
    echo "  claude-code, cursor, windsurf, copilot, cline, gemini-cli,"
    echo "  kiro, trae, goose, opencode, universal"
    echo ""
    echo "Examples:"
    echo "  $0                     # Auto-detect and install"
    echo "  $0 --platform windsurf-project  # Force Windsurf project install"
    echo "  $0 --dry-run           # Show where it would install"
}

main() {
    local platform=""
    local dry_run=false

    # Parse arguments
    while [ $# -gt 0 ]; do
        case "$1" in
            --platform)
                platform="$2"
                shift 2
                ;;
            --all)
                platform="all"
                shift
                ;;
            --dry-run)
                dry_run=true
                shift
                ;;
            --help|-h)
                show_help
                exit 0
                ;;
            *)
                log_error "Unknown option: $1"
                show_help
                exit 1
                ;;
        esac
    done

    # Detect platform if not specified
    if [ -z "$platform" ]; then
        platform=$(detect_platform)
        log_info "Detected platform: $platform"
    fi

    if [ "$platform" = "all" ]; then
        log_info "Installing to all detected platforms..."
        local detected=$(detect_platform)
        local install_path=$(get_install_path "$detected")
        if [ -n "$install_path" ]; then
            if [ "$dry_run" = true ]; then
                log_info "[DRY RUN] Would install to: $install_path"
            else
                install_skill "$detected" "$install_path"
            fi
        fi
    elif [ "$platform" = "unknown" ]; then
        log_error "Could not detect platform. Use --platform to specify."
        echo ""
        show_help
        exit 1
    else
        local install_path=$(get_install_path "$platform")
        if [ "$dry_run" = true ]; then
            log_info "[DRY RUN] Would install to: $install_path"
        else
            install_skill "$platform" "$install_path"
        fi
    fi
}

main "$@"
