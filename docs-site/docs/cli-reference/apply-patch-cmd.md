---
sidebar_position: 21
title: "apply-patch"
description: "Apply patch from diff file or cherry-pick"
---

# `apply-patch` Command

Apply a patch from a unified diff file or cherry-pick an existing patch operation to a different base snapshot.

## Usage

```bash
batho apply-patch --root /path/to/repo --base-snapshot SNAPSHOT_ID [options]
```

## Flags

| Flag | Default | Description |
|------|---------|-------------|
| `--root` | required | Path to repository root |
| `--base-snapshot` | required | Base snapshot ID to apply patch to |
| `--diff-file` | none | Path to unified diff file |
| `--patch-id` | none | Patch operation ID to cherry-pick |
| `--dry-run` | off | Preview without applying |

## Examples

### Apply from Diff File

```bash
# Apply patch from unified diff
batho apply-patch --root . \
  --base-snapshot batho_project_abc123_20260501T100000Z \
  --diff-file changes.diff

# Preview before applying
batho apply-patch --root . \
  --base-snapshot batho_project_abc123_20260501T100000Z \
  --diff-file changes.diff \
  --dry-run
```

### Cherry-pick Existing Patch

```bash
# Cherry-pick a patch to different snapshot
batho apply-patch --root . \
  --base-snapshot batho_project_new_20260520T100000Z \
  --patch-id batho_uuid_20260517T120000Z

# Preview cherry-pick
batho apply-patch --root . \
  --base-snapshot batho_project_new_20260520T100000Z \
  --patch-id batho_uuid_20260517T120000Z \
  --dry-run
```

## Diff File Format

The diff file should be in unified diff format:

```diff
--- a/src/auth.py
+++ b/src/auth.py
@@ -10,5 +10,7 @@
 def login(username, password):
+    """Authenticate user."""
     if validate(username, password):
         return True
+    log_attempt(username)
     return False
```

## Use Cases

- **Replay changes**: Apply the same diff to a different snapshot
- **Cherry-pick**: Apply a specific patch to a different branch/snapshot
- **Testing**: Verify patches work on different base states
- **Migration**: Move changes between snapshot lineages

## Related Commands

- `patch` - Apply incremental patches via scan or diff
- `cherry-pick` - Dedicated cherry-pick command
- `patch-info` - Show patch details before applying
