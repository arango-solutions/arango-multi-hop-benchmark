---
description: Production-ready mandate - never simplify away completeness in error handling, edge cases, security, tests, observability, or config
alwaysApply: true
---

# Comprehensiveness Over Simplification

> **"If a feature ships incomplete, it didn't ship—it leaked."**

You are building **production systems**. Simplification is the enemy of completeness.

## Completeness Dimensions

Every piece of work must address ALL of the following. Skipping any is a defect.

### Error Handling
- No swallowed errors — every `catch`/`if err != nil` must DO something
- Descriptive messages — WHAT failed, WITH WHAT input, WHY
- Context wrapping — `fmt.Errorf("loading config: %w", err)`
- Graceful degradation over crashing

### Edge Cases
Every function must handle: empty/nil inputs, boundary values, invalid inputs, unicode/special chars, concurrent access.

### Configuration Over Hardcoding
If a value could EVER differ across dev/staging/prod, it must be configurable.

### Test Completeness
Cover: happy path, error paths, edge cases, concurrency, regressions.

### Observability
Structured logging (not `fmt.Println`), metrics, tracing, health checks, alertable events.

### Security
Input validation at boundaries, no secrets in code/logs, auth/authz checks, least privilege.

### Documentation
Public function docstrings, README updates, API docs with examples, architecture notes for non-obvious decisions.

### UI/UX (Frontend)
Handle: loading, error, empty, success states. Accessibility (ARIA, keyboard nav). Responsive design.

### Data Integrity
Validate at boundaries, database constraints, transaction safety, idempotency.

### Performance
Pagination, caching, lazy loading, indexing, connection pooling.

## Anti-Patterns (NEVER Do)

| Anti-Pattern | Consequence |
| --- | --- |
| Happy Path Only | Production incidents |
| "We'll Add That Later" | "Later" never comes |
| Empty Catch Blocks | Hidden failures |
| Magic Numbers | Unmaintainable code |
| Copy-Paste Coding | Divergent behavior over time |
| Console.log Debugging | Noise in production logs |

## The Mantra

> **"Complete is better than clever. Robust is better than fast. Production-ready is the only ready."**

When in doubt, do MORE, not less.
