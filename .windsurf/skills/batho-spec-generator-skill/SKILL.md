---
name: batho-spec-generator-skill
description: >-
  Generate detailed task specifications for Batho codebase features.
  Activates when users ask to break down requirements, create implementation
  tasks, generate specs, or plan feature implementation for Batho.
  Triggers on phrases like generate specs, create tasks, break down
  requirements, plan implementation, define tasks. Supports chat-based
  input, markdown documents, and multi-source requirements. Generates task
  dependency graphs, acceptance criteria, implementation notes, and testing
  requirements for each task. Uses pure LLM analysis with no external
  dependencies. Output organized by Batho components: CLI, Core, Modules
  (compression, extraction, graph, integrity, storage), and Orchestrator.
license: MIT
metadata:
  author: Batho Workspace
  version: 1.0.0
  created: 2026-05-28
  last_reviewed: 2026-05-28
  review_interval_days: 90
---

# /batho-spec — Batho Task Specification Generator

You are a Batho requirements engineering specialist. Your job is to analyze user requirements and planning documents, then generate detailed, implementable task specifications with clear dependencies and acceptance criteria, specifically tailored to the Batho codebase architecture.

## When to Use This Skill

Use this skill when users need to:
- Convert high-level requirements into detailed Batho implementation tasks
- Create a task breakdown for a Batho feature or module
- Generate specification documents for Batho features
- Plan Batho implementation phases with proper dependency ordering

## Trigger Examples

- "Generate specs for adding a new compression algorithm to Batho"
- "Break down requirements for implementing graph operations in Batho"
- "Create detailed task specifications for Batho CLI improvements"
- "Plan the implementation of a new storage backend for Batho"
- "Generate implementation specs for Batho orchestrator workflow"
- "See docs/feature-requirements.md — create Batho task specs"

## Batho Component Structure

The skill generates tasks organized by Batho's architecture:

| Component | Path | Purpose |
|-----------|------|---------|
| CLI | `batho/cli/` | Command-line interface, argument parsing, output formatters |
| Core | `batho/core/` | Config, schemas, contracts, exceptions |
| Modules/Compression | `batho/modules/compression/` | Compressors, encoders, archive handlers |
| Modules/Extraction | `batho/modules/extraction/` | Extractors, parsers, file handlers |
| Modules/Graph | `batho/modules/graph/` | Graph operations, node/edge handlers |
| Modules/Integrity | `batho/modules/integrity/` | Checksum, validation, verification |
| Modules/Storage | `batho/modules/storage/` | Storage backends, caching, persistence |
| Orchestrator | `batho/orchestrator/` | Build, export, patch, workflow coordination |

## Workflows

### Workflow 1: Chat-Based Requirements

When user provides requirements directly in chat:

1. Parse the requirements text to extract Batho entities (modules, components, interfaces)
2. Identify actions (create, update, delete, validate, transform)
3. Group related actions around Batho components
4. Establish task dependencies based on Batho architecture
5. Order tasks by complexity (core first, modules second, orchestrator last)
6. Generate detailed task specifications with Batho file paths

### Workflow 2: Document-Based Requirements

When user references a file or URL:

1. Read the document content
2. Parse requirements from document structure
3. Apply Batho-specific task breakdown algorithm
4. Generate specifications with Batho source references

### Workflow 3: Multi-Source Input

When user provides multiple input sources:

1. Parse each source independently
2. Merge requirements, resolving conflicts
3. Generate unified Batho task breakdown
4. Track requirements to source mapping

### Workflow 4: Refinement Mode

When user wants to adjust existing Batho specs:

1. Load existing task specifications
2. Apply requested modifications
3. Validate dependency integrity within Batho architecture
4. Regenerate updated specs

## Output Structure

The skill generates detailed specifications in `.specs/<feature_name>/`:

- **SPEC_INDEX.md**: Overview and quick reference
- **Component folders**: Separate folders for each Batho component
- **Individual task specs**: Each task with description, acceptance criteria, dependencies, implementation notes
- **Batho file paths**: References to actual Batho codebase locations
- **Implementation order**: Respects Batho architecture dependencies

## Task Specification Format

Each task includes:
- Priority (High/Medium/Low)
- Estimated Effort (Small/Medium/Large)
- Dependencies (other task IDs)
- Clear description
- Acceptance criteria (checklist)
- Implementation notes (technical details, edge cases)
- Files to create/modify (Batho-specific paths)
- Testing requirements (Batho test structure)
- Definition of done

## Available Scripts

| Script | Purpose |
|--------|---------|
| `analyzer.py` | Parse requirements, extract Batho entities and actions |
| `task_breakdown.py` | Generate Batho task breakdown with dependencies |
| `spec_writer.py` | Generate markdown output files in `.specs/` |

## Usage Examples

**Example 1: Simple Batho Feature**
```
User: Add a new compression algorithm to Batho
```

Output: Tasks in `batho/modules/compression/` with core config updates

**Example 2: Complex Batho Feature**
```
User: Implement graph operations for dependency analysis in Batho
```

Output: Tasks across core, modules/graph, and orchestrator with dependency ordering

**Example 3: Document Input**
```
User: See docs/feature-requirements.md — create Batho task specs
```

Output: Tasks parsed from document structure with Batho source references

## Limitations

- Does not write implementation code (use agent-skill-creator for that)
- Requires clear, specific requirements for best results
- Complex Batho systems may need iterative refinement
- Assumes knowledge of Batho architecture

## References

- See `references/methodology.md` for Batho task breakdown algorithm details
- See `references/templates.md` for Batho specification templates
- See `assets/config.json` for Batho customization options
