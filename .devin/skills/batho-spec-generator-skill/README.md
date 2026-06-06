# batho-spec-generator-skill

A Batho-specific skill that generates detailed task specifications for Batho codebase features. Part of the Batho workspace.

## Overview

The batho-spec-generator-skill converts high-level requirements into detailed, implementable task specifications tailored to Batho's architecture:
- Task dependency graphs
- Acceptance criteria
- Implementation notes with Batho file paths
- Testing requirements
- Risk assessments
- Output organized by Batho components (CLI, Core, Modules, Orchestrator)

## Trigger

Invoke with `/batho-spec` followed by your requirements:

```
/batho-spec Add a new compression algorithm to Batho
/batho-spec Create detailed tasks for graph operations in Batho
/batho-spec Plan the implementation of a new storage backend
```

## Installation

### Auto-Install (Recommended)

The skill is pre-installed in the Batho workspace at `.windsurf/batho-spec-generator-skill/`.

### Manual Installation

```bash
cd .windsurf/batho-spec-generator-skill
./install.sh
```

### Platform-Specific Installation

```bash
# Windsurf project
./install.sh --platform windsurf-project

# Claude Code
./install.sh --platform claude-code

# Cursor
./install.sh --platform cursor-project

# All platforms
./install.sh --all
```

## Usage

### Basic Usage

```bash
# Analyze requirements and generate specs
python scripts/analyzer.py --input "Add a new compression algorithm to Batho"
python scripts/task_breakdown.py --requirements "Add a new compression algorithm to Batho"
python scripts/spec_writer.py --tasks task_breakdown.json --output .specs/compression-algorithm --detailed
```

### Combined Pipeline

```bash
# Run full pipeline
python -c "
import json
from scripts.analyzer import RequirementsAnalyzer
from scripts.task_breakdown import TaskBreakdownGenerator
from scripts.spec_writer import SpecificationWriter

# Step 1: Analyze
analyzer = RequirementsAnalyzer()
result = analyzer.analyze('Add a new compression algorithm to Batho')
analysis_data = {
    'entities': [{'name': e.name, 'type': e.entity_type, 'description': e.description} for e in result.entities],
    'actions': [{'name': a.name, 'type': a.action_type, 'target': a.target, 'description': a.description} for a in result.actions],
    'components': [{'name': c.name, 'description': c.description, 'entities': c.entities, 'actions': c.actions} for c in result.components]
}

# Step 2: Generate tasks
generator = TaskBreakdownGenerator()
task_result = generator.generate(analysis_data)
task_data = {
    'tasks': [{'id': t.id, 'name': t.name, 'description': t.description, 'priority': t.priority, 'effort': t.effort, 'dependencies': t.dependencies, 'component': t.component, 'files_to_create': t.files_to_create, 'implementation_notes': t.implementation_notes, 'testing_requirements': t.testing_requirements} for t in task_result.tasks],
    'dependency_graph': task_result.dependency_graph,
    'implementation_order': task_result.implementation_order,
    'warnings': task_result.warnings,
    'metadata': task_result.metadata
}

# Step 3: Write output
writer = SpecificationWriter()
writer.write_detailed_specs(task_data, '.specs/compression-algorithm', 'Compression Algorithm')
print('Specification written to .specs/compression-algorithm/')
"
```

### Via IDE Chat

Simply type in your IDE chat:

```
/batho-spec Implement graph operations for dependency analysis in Batho
```

The skill will generate detailed specs in `.specs/<feature_name>/` with component folders.

## Input Sources

### Chat-Based Input

Direct requirements in the chat:
```
/batho-spec Add a new storage backend to Batho
```

### Document-Based Input

Reference existing documents:
```
/batho-spec See docs/feature-requirements.md - generate Batho task specs
```

### Multi-Source Input

Combine multiple sources:
```
/batho-spec Based on batho.yaml and docs/user-stories.md, create task specs
```

## Output Structure

The skill generates detailed specifications in `.specs/<feature_name>/`:

```
.specs/<feature_name>/
├── SPEC_INDEX.md
├── cli/
│   ├── T1_xxx.md
│   └── ...
├── core/
│   ├── T2_xxx.md
│   └── ...
├── modules/
│   ├── compression/
│   │   └── ...
│   ├── extraction/
│   │   └── ...
│   └── graph/
│       └── ...
└── orchestrator/
    └── ...
```

### Executive Summary
- Overview of the Batho feature
- Component breakdown with task counts
- Priority distribution

### Task Dependency Graph
- Mermaid diagram showing task relationships
- Visual representation of dependencies

### Individual Task Specs
Each task includes:
- Priority and effort estimates
- Dependencies
- Detailed description
- Acceptance criteria (checklist)
- Implementation notes
- Files to create/modify (Batho-specific paths like `batho/modules/compression/`)
- Testing requirements (Batho test structure)

### Implementation Order
- Ordered list of tasks for sequential execution
- Respects Batho architecture dependencies

### Risk Assessment
- Identified risks with mitigations

## Batho Component Structure

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

## Configuration

Customize behavior via `assets/config.json`:

```json
{
  "analysis": {
    "min_entity_length": 2,
    "max_entities": 50,
    "component_keywords": {
      "cli": ["cli", "command", "argument", "parser"],
      "core": ["core", "schema", "contract", "exception"],
      "compression": ["compress", "compressor", "encoder", "decoder"],
      "extraction": ["extract", "extractor", "parser", "file"],
      "graph": ["graph", "node", "edge", "traversal"],
      "integrity": ["checksum", "hash", "integrity", "validation"],
      "storage": ["storage", "backend", "cache", "persistence"],
      "orchestrator": ["orchestrator", "build", "export", "patch"]
    }
  },
  "task_generation": {
    "max_tasks": 50,
    "min_tasks": 3
  },
  "output": {
    "include_mermaid": true,
    "default_output_file": ".specs/feature"
  }
}
```

## Scripts

| Script | Purpose |
|--------|---------|
| `analyzer.py` | Parse requirements, extract Batho entities and actions |
| `task_breakdown.py` | Generate Batho task breakdown with dependencies |
| `spec_writer.py` | Generate markdown output files in `.specs/` |

## Examples

### Example 1: Simple Batho Feature

**Input:**
```
/batho-spec Add a new compression algorithm to Batho
```

**Output:** Tasks in `batho/modules/compression/` with core config updates

### Example 2: Complex Batho Feature

**Input:**
```
/batho-spec Implement graph operations for dependency analysis in Batho
```

**Output:** Tasks across core, modules/graph, and orchestrator with dependency ordering

### Example 3: Document Input

**Input:**
```
/batho-spec See docs/feature-requirements.md - generate Batho task specs
```

**Output:** Tasks parsed from document structure with Batho source references

## Integration with agent-skill-creator

The batho-spec-generator-skill produces specifications that can be fed directly to agent-skill-creator for implementation:

```bash
# Generate specs
/batho-spec Add a new compression algorithm to Batho

# Then use agent-skill-creator to implement
/agent-skill-creator Implement the tasks in .specs/compression-algorithm/
```

## Troubleshooting

### Issue: Too many or too few tasks
**Solution:** Adjust `max_tasks` and `min_tasks` in config.json

### Issue: Missing dependencies
**Solution:** Provide more detailed requirements or manually add dependencies in refinement mode

### Issue: Circular dependencies detected
**Solution:** The system automatically breaks cycles by removing the weakest dependency

### Issue: Poor task descriptions
**Solution:** Provide more specific, detailed requirements

### Issue: Wrong component detected
**Solution:** Use Batho-specific keywords in requirements (e.g., "compressor" for compression module)

## License

MIT

## Version

1.0.0
