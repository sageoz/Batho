# Task Breakdown Methodology

This document describes the algorithm and heuristics used by the spec-generator-skill to break down requirements into implementable tasks.

## Overview

The task breakdown process consists of three main phases:

1. **Analysis Phase** (`analyzer.py`): Parse requirements to extract entities, actions, and components
2. **Generation Phase** (`task_breakdown.py`): Generate tasks with dependencies
3. **Output Phase** (`spec_writer.py`): Format tasks into markdown specifications

## Analysis Phase

### Entity Extraction

Entities are nouns and noun phrases that represent:
- **Components**: Services, APIs, modules, controllers
- **Data Structures**: Models, schemas, entities
- **Interfaces**: Endpoints, APIs, contracts
- **Services**: External integrations, workers, queues

**Extraction Algorithm:**

1. Scan for component keywords (service, api, controller, handler, etc.)
2. Scan for data structure keywords (user, account, session, etc.)
3. Identify custom patterns (CamelCase names, quoted interfaces)
4. Classify each entity by type
5. Normalize names to readable format

**Example:**

Input: "Build a user authentication system with JWT tokens"
- Entities: "Authentication System" (component), "User" (data_structure), "JWT Token" (data_structure)

### Action Extraction

Actions are verbs that represent operations to be performed:

| Action Type | Keywords |
|-------------|----------|
| Create | create, add, register, new, insert |
| Read | get, fetch, retrieve, read, list, search |
| Update | update, modify, edit, change, patch |
| Delete | delete, remove, drop, unregister |
| Validate | validate, verify, check, authenticate |
| Transform | convert, transform, map, serialize |
| Notify | send, notify, push, emit, broadcast |
| Store | save, store, persist, cache, index |

**Extraction Algorithm:**

1. Split requirements into sentences
2. For each sentence, identify action verbs
3. Extract the target of each action
4. Classify by action type
5. Also detect modal requirements (should, must, need, require)

### Component Identification

Components group related entities and actions into logical units:

| Component | Keywords |
|-----------|----------|
| Authentication | auth, login, password, token, session, credential, oauth |
| API Layer | api, endpoint, route, rest, http, request, response |
| Data Layer | database, storage, cache, repository, model, schema |
| Business Logic | payment, order, product, user, account, transaction |
| User Interface | ui, interface, page, screen, component, button, form |

**Algorithm:**

1. For each entity, check which component keywords it contains
2. Group entities by component
3. Assign actions to components based on their targets
4. Establish component dependencies based on standard architecture patterns

## Generation Phase

### Task Templates

Each component has predefined task templates:

**Data Layer:**
- Design database schema
- Create data models
- Implement repository pattern
- Add data validation
- Create migration scripts

**Authentication:**
- Implement user registration
- Implement login functionality
- Create token generation
- Add password hashing
- Implement session management
- Add OAuth2 support

**API Layer:**
- Define API endpoints
- Create request/response schemas
- Implement route handlers
- Add request validation
- Create error handling middleware
- Implement rate limiting

**Business Logic:**
- Implement business rules
- Create service layer
- Add business validations
- Implement transactions
- Create workflow handlers

**User Interface:**
- Design UI components
- Create form handlers
- Implement state management
- Add responsive styling
- Implement user feedback
- Create navigation

### Dependency Resolution

Dependencies are established based on:

1. **Component Order**: Data Layer → Authentication → Business Logic → API Layer → UI
2. **Task Prerequisites**: Infrastructure tasks come first
3. **Explicit Dependencies**: Tasks that must complete before others can start

**Algorithm:**

1. Assign base dependencies based on component
2. Build dependency graph
3. Detect circular dependencies
4. Break cycles by removing weakest dependency
5. Perform topological sort for implementation order

### Priority Assignment

Tasks are prioritized based on:

| Priority | Criteria |
|----------|----------|
| High | Has dependencies, Infrastructure component |
| Medium | No dependencies, Authentication/API component |
| Low | Optional features, UI enhancements |

### Effort Estimation

Effort is estimated based on:

- Number of entities and actions in requirements
- Component complexity
- Number of files to create/modify

| Effort | Complexity Score |
|--------|------------------|
| Small | < 2 |
| Medium | 2-5 |
| Large | > 5 |

## Output Phase

### Markdown Generation

The output includes:

1. **Executive Summary**: Overview of tasks and components
2. **Dependency Graph**: Mermaid diagram showing task relationships
3. **Task Specifications**: Detailed specs for each task
4. **Implementation Order**: Ordered list for execution
5. **Risk Assessment**: Identified risks with mitigations

### Task Specification Format

Each task includes:

```markdown
### T1: Task Name 🔴

**Priority**: High | **Effort**: Medium | **Component**: Data Layer

**Dependencies**: T1, T2

#### Description
Task description here...

#### Acceptance Criteria
- [ ] Criterion 1
- [ ] Criterion 2

#### Implementation Notes
- Note 1
- Note 2

#### Files to Create
- `path/to/file.py`

#### Testing Requirements
- Test requirement
```

## Usage Examples

### Example 1: Simple Requirements

Input: "Build a user authentication system"

Output: ~8 tasks covering:
- Project setup (T1-T2)
- Data models (T3-T5)
- Authentication logic (T6-T9)
- API endpoints (T10-T12)

### Example 2: Complex Requirements

Input: "Create an e-commerce platform with cart, checkout, payment processing"

Output: ~20 tasks across:
- Infrastructure (T1-T2)
- Data Layer (T3-T8)
- Authentication (T9-T13)
- Business Logic (T14-T18)
- API Layer (T19-T22)
- User Interface (T23-T26)

### Example 3: Document Input

Input: "See docs/requirements.md - generate specs"

Output: Tasks parsed from document structure with source references

## Configuration

The behavior can be customized via `config.json`:

```json
{
  "max_tasks": 50,
  "min_tasks": 3,
  "min_entity_length": 2,
  "include_mermaid": true,
  "include_toc": true
}
```

## Limitations

- Requires clear, specific requirements for best results
- Complex systems may need iterative refinement
- Does not write implementation code
- Dependency detection may miss implicit relationships

## Troubleshooting

### Issue: Too many or too few tasks

**Solution**: Adjust `max_tasks` and `min_tasks` in config

### Issue: Missing dependencies

**Solution**: Review requirements for implicit dependencies, use refinement mode

### Issue: Circular dependencies detected

**Solution**: The system automatically breaks cycles by removing weakest dependency

### Issue: Poor task descriptions

**Solution**: Provide more detailed requirements input
