# Roadmap

Goal: a deployed, public budget tracker at a real URL, built to a standard worth discussing in interviews: security, data protection, infrastructure as code, tests, and LLM evals.

Working mode: built with Claude Code, every diff reviewed by the owner. Conventions are in `CLAUDE.md` and `.claude/rules/`.

Legend: `[ ]` not started, `[~]` in progress, `[x]` done.

## 0. Project setup  [x] 2026-09-09
- [x] CLAUDE.md, path-scoped rules, lint and test hooks, permissions, `/feature` skill
- [x] pytest and vitest scaffolding with first real tests
- [x] CI on GitHub Actions (lint, typecheck, tests, build)

## 1. Parse and categorise  (current)
- [x] Frontend stack decided 2026-09-09: stay on Vite + React as an SPA, add TanStack Query for server state. Next.js deferred to the second project. See the decisions log.
- [ ] Extract structured fields (counterparty, reference) from descriptions. `shape()` in `main.py` is the tested anonymisation primitive to build on. The LLM regex-inference spike was removed on 2026-09-09 pending a decision on approach; the owner expects to inspect a few real samples per shape first to name the parts semantically.
- [ ] Categorise transactions against a preset category list
- [ ] Show categories in the table and allow manual override

## 2. Persistence and accounts
- [ ] Decide database: Postgres on Neon or Supabase (recommended) vs DynamoDB
- [ ] Data model: users, imports, transactions, categories
- [ ] Decide auth: Cognito (AWS-native, more work) vs Clerk (faster)
- [ ] Per-user data isolation enforced at the query layer, with tests that prove it

## 3. Data protection
- [~] Gemini API tier: free tier during development (decided 2026-09-09). Google may use prompts for product improvement and human review on this tier, so only synthetic or scrubbed CSVs are used in development, never real statements. Revisit before any deploy with real users.
- [ ] Stop sending raw rows for column mapping: send headers plus shaped or masked rows instead of the first ten lines.
- [ ] Mask word tokens in the regex-inference samples so structure survives but merchant and personal names do not.
- [ ] Decide the production model provider: Gemini developer API vs Vertex AI (DPA, London region) vs Bedrock (same AWS account and region as the deploy). Recommendation: Bedrock for production, Gemini for local development.
- [ ] Write `docs/data-protection.md`: data inventory, data flows, processors, retention, lawful basis, user rights. Lightweight DPIA format.
- [ ] Explicit opt-in screen before the first upload, naming the processor and what is sent.
- [ ] Account deletion removes all user data; data export available.

## 4. Deploy
- [ ] Terraform: S3 + CloudFront for the app, Lambda + API Gateway for the API, Secrets Manager for the Gemini key
- [ ] GitHub Actions deploy via OIDC federation, no long-lived AWS keys
- [ ] Public URL with a clear data-handling notice
- [ ] Threat model and data-flow summary in README, linking to `docs/data-protection.md` (owner writes this)

## 5. Quality and evals
- [ ] Playwright end-to-end test for the CSV upload flow
- [~] Eval set: sample CSVs from several banks with expected column mappings, run in CI.
      Synthetic fixtures for NatWest, Amex, Monzo, Starling and HSBC live in
      `sample-data/` (added 2026-09-09). Expected mappings and the CI runner are
      still to do. `hsbc.csv` is headerless and currently loses its first row
      silently -- see `sample-data/README.md`.
- [ ] Observability: structured logs and error alerting

## 6. Product
- [ ] Analytics (PostHog or similar), landing copy, changelog
- [ ] Get five real users and record what changed as a result

## Decisions log
- 2026-09-09: Parked the LLM regex-inference spike for description parsing. It sent six raw sample descriptions to Gemini to get parsing regexes back, was never wired into a response, and broke on CSVs with fewer than six distinct shapes. Removed from `main.py`; the tested `shape()` anonymiser is kept. Revisit the approach (likely: inspect real samples per shape by hand first) under milestone 1.
- 2026-09-09: Stay on the Gemini free tier during development. Real bank statements are not uploaded until the provider decision in milestone 3 is made.
- 2026-09-09: Frontend stack: Vite + React SPA with TanStack Query for server state. Next.js rejected for this project because the app is a static bundle talking to a Python API, so SSR buys nothing and a Next.js host would hide the S3 + CloudFront Terraform work that milestone 4 exists to demonstrate. Next.js goes to the second project, where SSR and a TypeScript backend actually apply. TanStack Query owns request state (in-flight, error, retry, cache) so hooks stop hand-rolling it; the cache earns its keep in milestone 2 when imports and transactions become persisted server state.
- 2026-09-09: Keep Python and FastAPI for the API. A TypeScript backend will be a separate project.
- 2026-09-09: AWS with Terraform for deployment. Vercel rejected because it hides the IaC work. GCP rejected on job-market grounds.
- 2026-09-09: Build agentically with owner review rather than hand-writing React.
