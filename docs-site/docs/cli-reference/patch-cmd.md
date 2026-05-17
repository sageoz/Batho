---
sidebar_position: 4
title: "patch & patches"
description: "Incremental patching commands"
---

# `patch`, `patches`, `apply-patch`, `cherry-pick` Commands

## `patch`

Apply incremental updates from scan, diff, or explicit files.

### Patch Options

| Flag | Default | Description |
|------|---------|-------------|
| `--scan` | off | Auto-scan for changes |
| `--dry-run` | off | Preview changes without applying |
| `--base-snapshot` | auto | Use specific snapshot as base |
| `--force-index-patch` | off | Force traditional index-based patching |
| `--diff` | none | Apply patch from unified diff |
| `files...` | none | Patch explicit changed files |

### Examples

```bash
# Auto-detect file changes and patch
batho patch --root /path/to/repo --scan

# Force traditional index-based patching (disable snapshot optimization)
batho patch --root . --scan --force-index-patch

# Patch from unified diff
batho patch --root /path/to/repo --diff /path/to/changes.diff

# Patch specific files
batho patch --root /path/to/repo src/a.py src/b.py
```

## `patches`

List patch operations.

```bash
batho patches --root /path/to/repo --format timeline
```

## `patch-info`

Show patch operation details.

```bash
batho patch-info --root /path/to/repo --patch-id ID --format summary
```

## `apply-patch`

Apply patch from diff file.

```bash
batho apply-patch --root /path/to/repo --base-snapshot SNAP_ID --diff-file /path/to/changes.diff
```

## `cherry-pick`

Apply a patch to another snapshot.

```bash
batho cherry-pick --root /path/to/repo --patch-id PATCH_ID --target-snapshot SNAP_ID
```

## `patch-chain`

Show chain of patches for a snapshot.

```bash
batho patch-chain --root /path/to/repo --snapshot-id SNAP_ID --full
```
