# Specs

One directory per change, named by its **slug** — a short, stable, kebab-case
identifier derived from the ticket's subject and prefixed with the ticket id
(`adb-002-reuse-bedrock-clients`). The slug names the directory, the branch, and
every commit. Once set it never changes: renaming it orphans the spec directory
from its branch and its history.

```text
docs/specs/<slug>/
  ticket.md   — the original request, verbatim. A pasted ticket has no other
                system of record, so this directory becomes it.
  spec.md     — what & for whom. Acceptance criteria in EARS. Open questions.
  plan.md     — how. Affected layers, contracts, invariant → enforcement.
  tasks.md    — atomic tasks, the AC each covers, the tests that prove it.
```

## Phases

Each phase is a commit and a review gate. Nothing chains silently.

1. **Specify** (`spec.md`) — observable behavior only, never implementation.
2. **Blindspot pass** — hunt what *nobody* said, record it under *Open
   questions*, resolve every one with the requester. **This gate has no
   bypass:** no plan is written while an open question is unresolved.
3. **Plan** (`plan.md`) — the how, plus the enforcement boundary for every
   invariant.
4. **Tasks** (`tasks.md`) — ordered so the suite stays green at every step.
5. **Review** — an independent pass over the finished spec before the PR opens.

## Acceptance criteria: EARS

Number them `AC-1`, `AC-2`, … and use one of five patterns:

| Pattern | Shape |
|---|---|
| Ubiquitous | The system SHALL … |
| Event-driven | WHEN \<trigger\>, the system SHALL … |
| State-driven | WHILE \<state\>, the system SHALL … |
| Unwanted | IF \<condition\>, THEN the system SHALL … |
| Optional | WHERE \<feature is present\>, the system SHALL … |

**The observable-behavior test:** would the criterion still be correct if the
internals were rewritten in another language? If no, it is implementation
detail and belongs in `plan.md`. Conversely, an AC that nothing outside the
system can observe cannot become a test.

Every AC that states a bound states the **number** — the ceiling, the timeout,
the retry count, the rate with its denominator and window. Mark domain
invariants and boundary rules **(invariant)**; each one gets a single named
enforcement chokepoint in `plan.md`. An invariant enforced in two places is an
invariant enforced in neither.

## Status lifecycle

`Proposed` → `Accepted` → `Implemented` → `Superseded by <slug>`

## Relationship to `openspec/`

`openspec/` holds this project's earlier changes (the backend bootstrap and
`adb-001`) and its live capability specs under `openspec/specs/`. Those remain
the capability-level source of truth. This directory is the per-ticket spec
workflow going forward; a change that alters a capability's observable contract
should say so explicitly in its `plan.md` and name the `openspec/specs/` file it
affects.
