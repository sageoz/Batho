---
sidebar_position: 22
title: "cherry-pick"
description: "Cherry-pick patch to different base snapshot"
---

# `cherry-pick` Command

Apply a patch operation from one snapshot to a different target snapshot, enabling cross-branch or cross-snapshot patch reuse.

## Usage

```bash
batho cherry-pick --root /path/to/repo --patch-id PATCH_ID --target-snapshot SNAPSHOT_ID [options]
```

## Flags

| Flag | Default | Description |
|------|---------|-------------|
| `--root` | required | Path to repository root |
| `--patch-id` | required | Patch operation ID to cherry-pick |
| `--target-snapshot` | required | Target snapshot ID to apply patch to |
| `--dry-run` | off | Preview without applying |

## Finding IDs

```bash
# List patches to find patch IDs
batho patches --root . --format timeline

# List snapshots to find target snapshot IDs
batho snapshots --root .
```

## Examples

```bash
# Cherry-pick a patch to different snapshot
batho cherry-pick --root . \
  --patch-id batho_uuid_20260517T120000Z \
  --target-snapshot batho_project_target_20260520T100000Z

# Preview cherry-pick before applying
batho cherry-pick --root . \
  --patch-id batho_uuid_20260517T120000Z \
  --target-snapshot batho_project_target_20260520T100000Z \
  --dry-run

# Use short IDs
batho cherry-pick --root . \
  --patch-id uuid_20260517 \
  --target-snapshot target_20260520
```

## How It Works

1. Loads the patch operation from the source
2. Validates that the patch can apply to the target snapshot
3. Applies the entity/relationship changes to the target
4. Creates a new patch operation in the target's chain
5. Updates the target snapshot with the changes

## Conflict Resolution

If the patch cannot be cleanly applied (e.g., entities already modified), the command will:

- Show a detailed error message
- Indicate which entities/relationships conflicted
- Suggest using `--dry-run` to preview conflicts

## Use Cases

- **Backporting**: Apply a fix from main to a release branch snapshot
- **Feature reuse**: Apply a feature patch across multiple project snapshots
- **Testing**: Verify patches work on different base states
- **Disaster recovery**: Reconstruct a snapshot by applying patches from another

## Related Commands

- `apply-patch` - General patch application command
- `patch-info` - Show patch details before cherry-picking
- `patch-chain` - View patch history for both source and target
