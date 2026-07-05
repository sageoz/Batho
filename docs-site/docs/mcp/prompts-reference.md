---
sidebar_position: 6
title: "Prompts & Resources Reference"
description: "Complete documentation for all 7 Batho MCP prompts and 2 resources"
---

# MCP Prompts & Resources Reference

Batho MCP Server publishes both prompts (onboarding guides/workflow templates) and resources (read-only datasets) to assist AI models.

## Prompts

Prompts are predefined templates that help models orchestrate their query flow when starting complex tasks. You can load these prompts in your MCP client.

### 1. `explore_codebase`
Guides agents through exploring an unfamiliar codebase in a logical sequence.
- **Parameters**:
  - `repo` (string, optional): Registered repo name.
  - `focus` (string, optional): One of `"architecture"`, `"dependencies"`, `"entry_points"`, `"communities"`. Default is `"architecture"`.
- **Optimal Tool Sequence**: `list_repos` → `graph_overview` → `graph_query` → `get_file_graph`.

### 2. `understand_function`
Assists agents in dissecting a specific function, class, or method.
- **Parameters**:
  - `function_name` (string, required): Name of the function/class/method.
  - `repo` (string, optional): Registered repo name.
- **Optimal Tool Sequence**: `search_entities` → `get_entity` → `trace_path`.

### 3. `analyze_file`
Focuses on analyzing a single file's internal structure and imports.
- **Parameters**:
  - `file_path` (string, required): File path relative to repo root.
  - `repo` (string, optional): Registered repo name.
- **Optimal Tool Sequence**: `get_file_graph` → `get_entity` → `graph_query`.

### 4. `trace_dependency`
Helps find the calling sequence or dependency chain between two entities.
- **Parameters**:
  - `source` (string, required): Source entity name.
  - `target` (string, required): Target entity name.
  - `repo` (string, optional): Registered repo name.
- **Optimal Tool Sequence**: `search_entities` (for both) → `trace_path`.

### 5. `review_changes`
Analyzes changes made in the latest patch/build run.
- **Parameters**:
  - `repo` (string, optional): Registered repo name.
  - `change_kind` (string, optional): Filter by `"added"`, `"removed"`, `"modified"`, or `"renamed"`.
- **Optimal Tool Sequence**: `get_delta` → `get_entity` → `graph_overview`.

### 6. `impact_analysis`
Traces the incoming dependents ("blast radius") of a function or class.
- **Parameters**:
  - `entity_name` (string, required): Target entity name.
  - `repo` (string, optional): Registered repo name.
- **Optimal Tool Sequence**: `search_entities` → `get_entity` (checking 'Incoming') → `trace_path` → `get_file_graph`.

### 7. `architecture_overview`
Orientation guide to get a fast, token-efficient architectural overview.
- **Parameters**:
  - `repo` (string, optional): Registered repo name.
- **Optimal Tool Sequence**: `graph_overview` (in summary mode).

---

## Resources

Resources are static or dynamic read-only endpoints containing metadata.

### 1. `batho://schema`
Returns a JSON schema defining the Batho graph ontology, including:
- **`entity_types`**: `FUNCTION`, `CLASS`, `METHOD`, `MODULE`, `VARIABLE`, etc.
- **`relation_types`**: `CALLS`, `IMPORTS`, `USES`, `REFERENCES`, `DEFINES`, `INHERITS`, etc.
- **`response_formats`**: Token size and descriptions for `summary`, `concise`, and `detailed`.
- **`change_kinds`**: `added`, `removed`, `modified`, `renamed`.

### 2. `batho://repos`
Returns a JSON list of registered repositories with their absolute path, name, and artifact availability.
