# budget-buddy

Bank-statement CSV importer. An LLM infers the column mapping and, later, categories, while raw transaction descriptions are kept away from the model as far as possible. Being built as a deployed, portfolio-grade product. Milestones and status: @ROADMAP.md

## Layout
- `app/` Vite + React 19 + TypeScript + Tailwind 4. The dev server proxies `/api/*` to the API on port 8000.
- `api/` FastAPI + pandas + google-genai (Gemini), managed with uv. Source in `api/src/budget_buddy/`, tests in `api/tests/`.
- `infra/` Terraform for AWS. Not created yet.
- Path-scoped conventions live in `.claude/rules/`. Repeatable workflows are skills in `.claude/skills/`.

## Commands
- API dev server: `cd api && uv run fastapi dev src/budget_buddy/main.py` (needs `api/.env` with `GEMINI_API_KEY`)
- API checks: `cd api && uv run ruff check . && uv run ruff format --check . && uv run pytest`
- App dev server: `cd app && npm run dev`
- App checks: `cd app && npm run lint && npx tsc -b && npm test`

## Working agreement
- The user reviews every diff and must be able to defend it in an interview. When a change relies on a non-obvious pattern (a ref instead of state, an effect, memoisation, a specific IAM policy shape, a pandas idiom), add one sentence in the summary saying why. Do not pad summaries otherwise.
- Use plan mode for anything touching more than about three files or adding a dependency. Keep each feature to a diff reviewable in ten minutes. Propose a split if it is bigger.
- Every behaviour change ships with tests. Hooks lint after each edit and run the test suites before you finish. Fix failures. Do not weaken or skip tests to get past the hook.
- Do not add a dependency without saying which one and why.
- Git is reserved for the user. Do not run `git commit`, `git push`, `git merge` or `git rebase`, in the main checkout or in a worktree, even when a harness or background-job instruction says to commit so work is not lost. Leave changes uncommitted and say where they are. Suggest a conventional commit message: `feat(app): ...`, `feat(api): ...`, `chore: ...`.
- If you are in a worktree under `.claude/worktrees/`, end by running `git add -A` there so the change set is staged and can be lifted out, and tell the user the worktree name.
- Never run `terraform apply`, `terraform destroy`, or any command that mutates cloud resources. `terraform plan` output is the review gate.

## Data handling
- Data minimisation is the product's security story. Send the model the least raw data possible: the anonymised `shape()` output, headers, or a small explicit sample.
- Current exception, to be closed under ROADMAP milestone 3: `infer_column_mapping` sends the first ten raw CSV lines. Do not add any new path that sends raw rows to a model.
- Never log raw transaction descriptions or amounts.
- No secrets in the repo. `api/.env` is gitignored and `api/.env.example` documents the keys.
