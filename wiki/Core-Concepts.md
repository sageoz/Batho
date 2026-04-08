# Core Concepts

Understanding these concepts is key to using Batho effectively.

---

## Code Graph

Batho converts your code into a graph.

### Entities

* Functions
* Classes
* Variables
* Imports

### Relationships

* CALLS → function calls
* IMPORTS → dependencies
* USES → variable usage
* DEFINES → ownership

---

## BSG (Batho Structured Graph)

BSG is Batho’s main output format.

It is:

* Structured
* Compressed
* Optimized for LLMs

---

## Snapshots (Time Machine)

Batho stores versioned states of your codebase.

You can:

* Compare versions
* Track changes
* Analyze evolution

---

## Incremental Patching

Instead of rebuilding everything:

* Only changed files are processed
* Much faster than full indexing
