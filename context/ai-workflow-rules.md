# Development Workflow

## Approach

Spec-driven. Context files define what and how; `contracts/` freezes interfaces; `features/` files define
each unit; `progress-tracker.md` defines current state. Implement against these — do not invent behavior.

## Order of Work

1. Brainstorm and decide (record in `progress-tracker.md` → Architecture Decisions).
2. Write the feature file `features/fNN_<name>.md` **before any code** for that feature.
3. Plan. 4. Implement (TDD for pure logic). 5. Verify. 6. Update docs and tracker.

## Scoping Rules

- One feature unit or subsystem at a time per agent. Small, verifiable increments.
- Do not combine unrelated system boundaries in one step.

## When To Split Work

Split if a step combines UI + data changes, unrelated modules, or behavior not defined in the specs.

## Handling Missing Requirements

- Do not invent product behavior. Missing → *Open Questions* in `progress-tracker.md`; continue unblocked work.

## Parallel Work

- One git worktree + branch per agent (`feat/fNN-<name>`); disjoint `Owned files`.
- Contracts frozen first (`api/app/models.py`, `api/app/profiles.py`, `contracts/README.md`, `web/lib/types.ts`).
- Model choice: orchestrator **Opus** (contracts, security-critical review, merges); implementers **Sonnet**.
- Agents report real command output; the orchestrator reviews before merging.

## Protected Foundation Components

`web/components/ui/**` (shadcn), `api/app/models.py`, `api/app/profiles.py`, `contracts/**`, `web/lib/types.ts`.

## Keeping Docs In Sync

Update the matching context file whenever work changes architecture, storage, standards, or scope.
Progress state must reflect the **actual** state.

## Before Moving To The Next Unit

1. Unit works end to end within scope. 2. No invariant violated. 3. Verification commands run, real
results seen. 4. Tracker + feature *Status Log* updated.
