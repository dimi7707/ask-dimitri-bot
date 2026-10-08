# <slug> — tasks

Ordered so the suite stays green at every step: a thin end-to-end slice before
breadth. Infrastructure the plan assumes (a migration, a flag, a queue, an
index) appears as its own explicit task, or it will not exist on the day the
code ships.

## 1. Baseline

- [ ] 1.1 Run the full suite and record the passing count to compare against
- [ ] 1.2 Reproduce the defect the ticket describes, and record what you saw

## 2. <Group>

- [ ] 2.1 <Task> — **AC-n**, `<file touched>`

## N. Verify nothing else regressed

- [ ] N.1 Confirm each new test fails against the unfixed code, so it guards
      the regression instead of passing vacuously
- [ ] N.2 Run the full suite and confirm it is green at the baseline count plus
      the new tests
- [ ] N.3 Tick the ticket's acceptance criteria and close it

---

## Definition of done

**This spec PR** (docs only): spec, plan, and tasks reviewed and merged.

**The implementing PR**: every task above checked, every AC covered by a named
test, suite green, lint clean.

## AC coverage

| AC | Task | Test that proves it |
|---|---|---|
