# Domain Documentation

Engineering agents use this repository's domain documentation before exploring or changing code.

## Read before work

- Read root `CONTEXT.md` when it exists.
- Read relevant architectural decisions under `docs/adr/`.
- If root `CONTEXT-MAP.md` exists in the future, follow it to every context relevant to the task.

Proceed silently when these files do not exist. Create or extend them only when domain terminology or a durable decision is actually resolved.

## Layout

EpiSignal currently uses a single context:

```text
/
├── CONTEXT.md
└── docs/
    └── adr/
```

If the system later develops independently owned bounded contexts, replace root `CONTEXT.md` with `CONTEXT-MAP.md`, keep system-wide ADRs under `docs/adr/`, and place context-specific `CONTEXT.md` and ADRs beside their owning package.

## Vocabulary

Use the canonical terms defined in `CONTEXT.md` in code, tests, issues, specifications, and reviews. Avoid synonyms that obscure the distinction between source, signal, event, observation, and location role.

If a needed concept is absent, reconsider whether the concept is real. When it is real, use the `domain-modeling` workflow to define it.

## ADR conflicts

Surface any conflict with an existing ADR explicitly. Do not silently override a recorded architectural decision.
