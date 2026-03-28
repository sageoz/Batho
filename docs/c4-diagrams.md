# C4 Diagram Generation

Batho supports automatic generation of enterprise-grade C4 architecture diagrams from indexed repositories.

## Overview

The C4 model provides a simple and effective way to communicate software architecture:
- **L1 - System Context**: High-level view of the system and its interactions with external actors
- **L2 - Container**: Shows the high-level technology building blocks (web apps, APIs, databases, etc.)
- **L3 - Component**: Detailed view of components within containers

## Features

- **Rule-based generation**: Automatically detects architecture patterns from code
- **Structurizr-compatible output**: Generates JSON compatible with Structurizr
- **LLM-friendly extensions**: Includes additional context optimized for AI consumption
- **Deterministic output**: Same input always produces the same diagram

## Usage

### Automatic Generation (Default)

C4 models are automatically generated during indexing:

```bash
uv run python -m batho index --root /path/to/repo
```

The C4 model will be saved to `.ctn/<index_id>/c4-model.json`

### On-Demand Generation

Generate C4 models from existing index:

```bash
uv run python -m batho c4 --root /path/to/repo [--output /path/to/output.json]
```

### Skip C4 Generation

To skip C4 generation during indexing:

```bash
uv run python -m batho index --root /path/to/repo --no-c4
```

## Output Structure

The generated C4 model includes:

```json
{
  "name": "Repository Name",
  "description": "C4 model generated from .ctn artifacts",
  "model": {
    "people": [...],           // External actors (L1)
    "softwareSystems": [...],  // Software systems (L1)
    "containers": [...],       // Containers (L2)
    "components": [...]        // Components (L3)
  },
  "views": {
    "systemContextViews": [...],  // L1 views
    "containerViews": [...],      // L2 views
    "componentViews": [...]       // L3 views
  },
  "properties": {
    "llm_extensions": {
      // LLM-friendly context
    }
  }
}
```

## Detection Rules

### External Systems (L1)

Automatically detected from import patterns:
- **Database**: SQLAlchemy, Django ORM, psycopg, asyncpg, etc.
- **External APIs**: requests, httpx, aiohttp, etc.
- **Message Queues**: celery, redis, rabbitmq, etc.
- **File System**: pathlib, os.path, shutil, etc.
- **Authentication**: auth0, jwt, oauth, etc.
- **Email**: smtplib, email, sendgrid, etc.
- **Cloud Platforms**: boto3, google.cloud, azure, etc.

### Containers (L2)

Identified from frameworks and directory structure:
- **Web Application**: Flask, Django, FastAPI, etc.
- **API Service**: REST/GraphQL frameworks
- **Database**: ORM usage patterns
- **CLI Tool**: Click, Typer, argparse
- **Background Worker**: Celery, RQ
- **Test Suite**: pytest, unittest
- **Documentation**: Markdown files

### Components (L3)

Derived from code entities:
- **Controllers**: Request handlers
- **Services**: Business logic
- **Models**: Data structures
- **Repositories**: Data access
- **Utilities**: Helper functions

## LLM Extensions

The generated model includes LLM-friendly context:

- **Executive Summary**: System overview and purpose
- **Architecture Overview**: Patterns and layers
- **Key Workflows**: Common request flows
- **Data Architecture**: Models and persistence
- **API Catalog**: Available endpoints
- **Business Domains**: Functional areas
- **Technical Risks**: Potential issues
- **Scalability Considerations**: Performance factors
- **Security Posture**: Security assessment
- **Development Guidelines**: Best practices
- **Onboarding Guide**: Developer guidance
- **Change Impact Analysis**: Critical areas
- **Performance Hotspots**: Bottlenecks
- **Integration Points**: External systems
- **Glossary**: Technical terms

## Integration with Tools

### Structurizr

The output can be imported into Structurizr for visualization:

```bash
# Download and install Structurizr CLI
# Import the model
structurizr import c4-model.json
```

### Custom Visualization

The JSON structure can be consumed by custom tools:

```python
import json

with open('.ctn/latest/c4-model.json') as f:
    model = json.load(f)

# Access systems
for system in model['model']['softwareSystems']:
    print(f"System: {system['name']}")

# Access containers
for container in model['model']['containers']:
    print(f"Container: {container['name']} ({container['type']})")
```

## Configuration

Currently, C4 generation uses rule-based heuristics. Future versions will support:

- Custom rule definitions
- Configuration files for domain-specific patterns
- Filtering options for large repositories

## Examples

### Web Application

For a Flask application:
- L1: Shows web app interacting with users and database
- L2: Web Application, Database containers
- L3: Controllers, Services, Models components

### CLI Tool

For a command-line tool:
- L1: Shows CLI tool interacting with file system and APIs
- L2: CLI Application, Configuration containers
- L3: Command handlers, utilities components

## Troubleshooting

### No C4 Model Generated

Ensure the repository has been indexed:
```bash
uv run python -m batho index --root /path/to/repo
```

### Empty Components

Components require entities with sufficient importance scores. Smaller repositories may only show L1 and L2 elements.

### Missing External Systems

Check that import relationships are captured in the graph.json file.

## Contributing

To extend the detection rules, modify:
- `batho_core/context/c4_generator.py` - Main generation logic
- `batho_core/context/c4_rules.py` - Rule definitions
- `batho_core/context/c4_llm_extensions.py` - LLM context generation
