---
sidebar_position: 4
title: "patch"
description: "Apply incremental updates from scan, diff, or explicit files"
---

# `patch` Command

Apply incremental updates from scan, diff, or explicit files. When snapshots are available, automatically uses true incremental patching for better performance.

## Usage

```bash
batho patch --root /path/to/repo [options]
```

## Flags

| Flag | Default | Description |
|------|---------|-------------|
| `--root` | required | Path to repository root |
| `--scan` | off | Auto-detect changes via file hash scan |
| `--diff` | none | Path to unified diff file |
| `--base-snapshot` | `None` | Base snapshot ID for incremental patching (auto-detects latest if omitted) |
| `--force-index-patch` | off | Force traditional index-based patching instead of incremental |
| `--snapshot` | off | Create snapshot after patching |
| `--dry-run` | off | Preview changes without applying them |
| `--max-file-size-kb` | `500` | Maximum file size in KB |
| `files...` | none | Changed files (absolute or relative) |

## Examples

```bash
# Auto-detect file changes and patch
batho patch --root /path/to/repo --scan

# Force traditional index-based patching (disable snapshot optimization)
batho patch --root . --scan --force-index-patch

# Patch from unified diff
batho patch --root /path/to/repo --diff /path/to/changes.diff

# Patch specific files
batho patch --root /path/to/repo src/a.py src/b.py

# Preview changes before applying
batho patch --root . --scan --dry-run

# Create snapshot after patching
batho patch --root . --scan --snapshot
```

## Related Commands

- [patches](/docs/cli-reference/patches-cmd) - List patch operations
- [patch-info](/docs/cli-reference/patch-info-cmd) - Show detailed patch information
- [patch-chain](/docs/cli-reference/patch-chain-cmd) - Show patch chain for a snapshot
- [apply-patch](/docs/cli-reference/apply-patch-cmd) - Apply patch from diff file or cherry-pick
- [cherry-pick](/docs/cli-reference/cherry-pick-cmd) - Cherry-pick patch to different snapshot
