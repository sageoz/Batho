# Usage Guide

## Basic Workflow

### 1. Index

```bash
batho index --root .
```

---

### 2. Generate structured output

```bash
batho bsg --root . --mode compressed
```

---

### 3. Apply updates

```bash
batho patch --root . --scan
```

---

## BSG Modes

| Mode         | Description        |
| ------------ | ------------------ |
| compressed   | LLM-ready          |
| full         | detailed graph     |
| hierarchical | directory overview |

---

## Query Example

```bash
batho query --root . --entity-type function --limit 50
```
