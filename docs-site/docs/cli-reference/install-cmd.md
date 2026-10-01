---
title: "batho install"
description: "Install the skill pack and register the MCP server with every detected coding-agent client"
---

# `batho install`

One command for agent setup: installs the five pack skills — `batho`, `batho-setup`, `batho-specs`, `batho-execute`, `batho-review` — to `~/.agents/skills` plus native mirrors, and registers the Batho MCP server in every detected coding-agent client's config.

## Description

`batho install` performs both halves of agent setup:

1. **Skill pack** — downloads the published batho-skills release (checksum-verified, size-capped) and installs it to the vendor-neutral `~/.agents/skills` path plus per-agent mirrors.
2. **MCP registration** — merges the stdio server entry (`batho mcp`) into each detected client's MCP config: `claude-desktop`, `claude-code`, `cursor`, `windsurf`, `vscode`, `codex`, `gemini`, `opencode`, `copilot`. Merge-not-clobber: only the `batho` key inside the client's server map is touched; every other server and setting is preserved. Writes are atomic (tmp + rename). Global scope only — no project files are written.

**Updating**: re-running `batho install` is the update path — when the installed pack version differs from the upstream release, the pack is re-fetched and re-synced (`force`); when it matches, the download is skipped (`skill pack already up to date`). The MCP registration is refreshed on every run. `batho mcp` start additionally auto-syncs a drifted pack (opt out via `skills.auto_install: false`; pin via `BATHO_VERSION`).

## Usage

```bash
batho install [options]
```

## Options

- `--agent NAME` — Force a specific agent's native dirs / MCP config (repeatable). Agents without MCP support (e.g. `roo`) get skills installed and a note that MCP was skipped.
- `--all` — Write every known agent's dirs and every supported client's MCP config (skip detection).
- `--project` — Install skills to `./.agents/skills` instead of the global dir (MCP registration stays global and is skipped with a note).
- `--version V` — Pin a skill-pack release version (e.g. `1.2.0` or `v1.2.0`).
- `--copy` — Copy instead of symlink for skill mirrors.
- `--force` — Overwrite existing skill dirs even without the `.batho-skill` marker.
- `--no-mcp` — Skip MCP server registration (skills only).

Exit code is `1` if any step failed (e.g. a corrupt client config — the error names the file; fix it and re-run). One broken client config never blocks the others.

## Examples

```bash
batho install                        # skills + MCP for every detected client
batho install --agent cursor         # one client only
batho install --all                  # every known agent's dirs + every supported client's config
batho install                        # re-run: updates the pack when upstream differs
batho install --no-mcp               # skill pack only
```
