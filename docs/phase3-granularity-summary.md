# Phase 3: Adaptive Granularity - Implementation Summary

## Overview

Phase 3 introduces an intelligent adaptive granularity system that automatically adjusts the level of detail in C4 models based on repository characteristics. This ensures optimal performance and readability for repositories of any size.

## Key Components

### 1. RepositoryAnalyzer (`granularity/analyzer.py`)
Analyzes repository characteristics to inform granularity decisions.

**Features:**
- Calculates entity count, coupling, and cohesion scores
- Detects domain boundaries and complexity metrics
- Categorizes repository size (small/medium/large/massive)
- Provides performance targets based on repository characteristics

**Key Metrics:**
```python
@dataclass
class RepositoryMetrics:
    entity_count: int
    avg_file_size: float
    coupling_score: float  # 0-1 scale
    cohesion_score: float  # 0-1 scale
    domain_count: int
    complexity_score: float
    size_category: str
    entity_importance: Dict[str, float]
```

### 2. GranularityDecisionEngine (`granularity/engine.py`)
Makes intelligent decisions about granularity level based on metrics.

**Granularity Levels:**
- **Fine**: Show all components (< 100 entities)
- **Medium**: Group related components (100-1000 entities)
- **Coarse**: High-level containers only (> 1000 entities)
- **Adaptive**: Dynamic based on repository characteristics

**Decision Process:**
- Rule-based decision matrix with weighted factors
- ML hooks for future enhancement
- Manual override support
- Performance optimization recommendations

### 3. ComponentGroupingManager (`granularity/grouping.py`)
Creates virtual groupings of components for better organization.

**Grouping Strategies:**
- **Domain**: Group by package/domain boundaries
- **Functional**: Group by similar responsibilities
- **Data Flow**: Group by data flow patterns
- **Team**: Group by team ownership (git history)
- **Hybrid**: Multiple strategies combined

### 4. ViewFilteringEngine (`granularity/filtering.py`)
Generates focused views of the C4 model.

**Filter Types:**
- Overview: High-level stakeholder view
- Domain-specific: Focused on particular domains
- Important: Components above importance threshold
- Progressive: Layered disclosure for exploration

### 5. GranularityCache (`granularity/cache.py`)
Caches decisions and metrics for performance.

**Features:**
- In-memory and disk caching
- TTL-based expiration
- Automatic cleanup
- Cache statistics

## Integration with C4Generator

The granularity system is tightly integrated with the C4Generator:

1. **Early Analysis**: Repository metrics are calculated before model generation
2. **Granularity Decision**: Determines what to include in the model
3. **Component Filtering**: Applies importance thresholds and limits
4. **Metadata Enrichment**: Adds granularity information to model metadata

## CLI Enhancements

New CLI options for granularity control:

```bash
batho c4 --root . --granularity fine
batho c4 --root . --grouping-strategy domain
batho c4 --root . --importance-threshold 0.5
batho c4 --root . --max-components 100
```

## Performance Targets

The system meets these performance targets:

- **Small repos** (< 100 entities): < 1 second
- **Medium repos** (100-1000 entities): < 3 seconds
- **Large repos** (1000-10000 entities): < 10 seconds
- **Massive repos** (> 10000 entities): < 30 seconds

## Test Coverage

Comprehensive test suite with 20 tests covering:
- Repository analysis for all size categories
- Granularity decision logic
- Component grouping strategies
- View filtering mechanisms
- Cache functionality
- Integration with C4Generator

## Benefits

1. **Performance**: Automatically optimizes model generation for large repositories
2. **Readability**: Produces cleaner, more focused diagrams
3. **Flexibility**: Allows manual overrides when needed
4. **Scalability**: Handles repositories from tiny to massive
5. **Intelligence**: Makes smart decisions based on code characteristics

## Future Enhancements

- ML-based granularity prediction
- Interactive granularity adjustment
- A/B testing of granularity decisions
- User feedback integration
- Advanced visualization of groupings

## Example Output

```json
{
  "generation_metadata": {
    "granularity": {
      "level": "medium",
      "reasoning": "Medium repository (500 entities) requires grouping",
      "confidence": 0.8,
      "settings": {
        "max_components": 500,
        "group_components": true,
        "importance_threshold": 0.3
      },
      "metrics": {
        "entity_count": 500,
        "size_category": "medium",
        "complexity_score": 0.5
      }
    }
  }
}
```

This adaptive granularity system ensures that Batho can effectively analyze and visualize repositories of any size, providing appropriate levels of detail without overwhelming users or sacrificing performance.
