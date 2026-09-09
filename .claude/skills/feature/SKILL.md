---
name: feature
description: Build one roadmap item end to end - scope it, plan it, implement with tests, run all checks, and hand over a review summary. Use when starting or continuing a feature.
argument-hint: [roadmap item or feature description]
disable-model-invocation: true
---

## Current state

Branch: !`git branch --show-current`
Working tree:
!`git status --short`

## Feature

$ARGUMENTS

## Procedure

1. **Scope.** Read `ROADMAP.md` and find the matching item. If the feature is not a single diff reviewable in about ten minutes, propose a split and stop until the owner picks a slice.
2. **Branch.** If on `main`, create `feat/<short-slug>` with `git switch -c`. If the working tree has unrelated changes, say so and stop.
3. **Plan.** Enter plan mode. The plan lists: files to touch, tests to add (named by behaviour), any decision that needs the owner, and any dependency with a one-line justification. Wait for approval.
4. **Implement.** Tests first for pure logic. Small steps. Keep the diff to the plan. If the plan turns out wrong, say so and re-plan rather than improvising.
5. **Verify.** Run the full checks from `CLAUDE.md` for whichever side changed. The stop hook will run the test suites again. If a manual check in the browser is useful, do it and report what you saw.
6. **Hand over.** Finish with:
   - What changed, in three to six bullets.
   - How to verify it manually, as commands or clicks.
   - **Why notes**: one line each for any non-obvious pattern the owner may be asked about in an interview. Maximum five. Skip if there are none.
   - Open questions or follow-ups.
   - A suggested conventional commit message. Do not commit.
7. **Roadmap.** Update the item's status in `ROADMAP.md` in the same diff.
