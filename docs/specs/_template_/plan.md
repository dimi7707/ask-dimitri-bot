# <slug> — plan

## Context

<The mechanism as it stands today, with file:line pointers and any measurement
that establishes the defect. Enough that a reader needs no other tab open.>

## Decisions

### <Decision, phrased as the choice made>

<Why. Then the alternatives considered and why each was rejected — a decision
with no rejected alternative is a default, not a decision.>

## Affected layers

| Layer | File | Change |
|---|---|---|

<State the dependency direction this change assumes, and keep it consistent
with whatever the repo documents.>

## Invariant → enforcement

<For every **(invariant)** criterion: the single chokepoint that enforces it,
and the concrete artifact that proves it. Name the test file, the schema
constraint, the index, the static check. "Enforced at the boundary" is not an
answer unless the boundary is named.>

| AC | Invariant | Chokepoint | Proof |
|---|---|---|---|

## Gates this change adds

<For every lint rule, type, static scan, or architecture test promised above:
what it rejects, and what still passes it. A gate weaker than the sentence
describing it reads as enforcement and is not.>

## Risks / trade-offs

<Each risk, then how it is handled — or the explicit decision to accept it.>

## Rollout & rollback

<Deployment order, flags, what the revert is, and the post-deploy signal that
tells you it worked.>

## ADR impact

<The architectural rule this establishes or changes, or an explicit "none". If
the repo keeps no ADRs, say so and record the decision here.>
