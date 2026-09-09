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
- [ ] **Layer A -- field-presence map.** Replace the flat `*_column` fields on
      `ColumnMapping` with a per-fact `FieldSource {column, purity}`, where purity is
      `exact` / `embedded` / `absent`, over a fixed fact list: date, amount, balance,
      payee, reference, category, txn_type, currency, notes. `exact` means take the
      column as-is; `embedded` is the only thing that triggers layer B. The question
      is no longer "is this column the payee" but "does this column *contain* the
      payee", which is what the fixtures actually demand: Monzo's payee is
      (`Name`, exact), NatWest's is (`Description`, embedded), Amex's category is
      absent.
- [x] **Column profiler** 2026-09-09, no model involved: per column, cardinality
      ratio, mean token count, mean length, case profile with its consistency
      fraction, fill rate, and cross-column token containment. Landed as
      `api/src/budget_buddy/profile.py` with `api/tests/test_profile.py` pinning the
      measurements below against the fixtures. Not yet wired into `main.py` -- layer A
      is its first consumer.
      Cardinality separates enum columns (NatWest `Type` 0.17, Starling `Spending
      Category` 0.50) and constants (`Account Name` 0.03) from per-transaction data.
      Correction to the original note: it does *not* separate free text from a clean
      payee column -- Monzo `Name` is 1.00 and Amex `Description` 0.87, so cardinality
      alone cannot answer that question. Token count and case do: Title Case with a low
      token count marks a bank-cleaned counterparty (Monzo `Name`, 1.6 tokens, Mixed)
      against a raw descriptor (NatWest `Description`, 6.9 tokens, 97% UPPER).
      Containment found Monzo `Name` is a subset of `Description` on 80% of rows, which
      is the "does this field include that data" relationship computed outright, and is
      silent on all four other fixtures. Making it usable needed three guards, each
      earned by a real false positive on Monzo's 16 columns: a 0.75 threshold (drops
      `Address` in `Description`, 0.67), dropping symmetric pairs since duplicate
      columns contain each other both ways (`Amount`/`Local amount`,
      `Currency`/`Local currency`, both 0.93), and requiring the container to be
      strictly wider by mean token count. Starling `Counter Party` and `Reference`
      reach only 0.50 and stay silent, as intended.
- [ ] **Bucket refinement** -- blocker for layer B, do this first. `shape()` collapses
      word runs, so the dominant bucket is a bare `W+` on three of five fixtures
      (14/23 Amex, 16/25 HSBC, 12/15 Monzo): `CR BRIGHTFORD LTD SALARY` and
      `DD VODAFONE LTD` share a shape, and one slot spanning the whole string makes
      slot assignment meaningless -- on exactly the banks that need extraction most.
      Fix with a positional token-frequency table per bucket: tokens recurring at a
      position across many rows are structural (`CR`, `DD`, `VIS`, `BP`, `)))`),
      near-unique ones are the payee. Pure computation, no model. Caveat to keep
      honest: "recurs often, therefore not personal" is a heuristic, not a guarantee
      -- a monthly payment to a named individual recurs too -- so back it with a known
      bank-prefix vocabulary rather than frequency alone.
- [ ] **Layer B -- slot assignment.** For `embedded` columns only, bucket rows by
      refined shape and have the model map each fact to a *slot index*, never a value:
      `"N4 DATE W+ , W+ , W+"` becomes `{card_last4: 0, date: 1, payee: 3,
      location: 4}`. Code applies that to every row in the bucket. Cost is O(distinct
      patterns) rather than O(rows) -- NatWest is 10 shapes for 36 rows -- and the
      model cannot invent a merchant when it only emits integers.
- [ ] **Categorise by set-to-set mapping.** When `category.purity == "exact"`, do not
      categorise transactions at all: send the distinct category strings (Monzo 10,
      Starling 10) and map that set onto the preset list in one call. Transaction rows
      are never involved. The bank's label is a high-priority hint, not authoritative,
      so `Transfers` may legitimately map to `Housing`. Cache on
      `(bank category set, category list version)`; allow a null target and fall back
      to payee-based categorisation for only those rows. Preset list lives in code for
      the first iteration and becomes user-defined later, which is why the cache key
      carries a list version from the start.
- [ ] Categorise by payee where no bank category exists: distinct payees only, never
      whole rows, and the cache stays warm across users.
- [ ] Show categories in the table and allow manual override, plus the bank-to-preset
      mapping as an inspectable, editable table -- the mapping is a stored object, not
      a per-row model guess.

## 2. Persistence and accounts
- [ ] Decide database: Postgres on Neon or Supabase (recommended) vs DynamoDB
- [ ] Data model: users, imports, transactions, categories
- [ ] Decide auth: Cognito (AWS-native, more work) vs Clerk (faster)
- [ ] Per-user data isolation enforced at the query layer, with tests that prove it

## 3. Data protection
- [~] Gemini API tier: free tier during development (decided 2026-09-09). Google may use prompts for product improvement and human review on this tier, so only synthetic or scrubbed CSVs are used in development, never real statements. Revisit before any deploy with real users.
- [ ] Narrow the column-mapping exception: replace the first ten raw lines with
      headers, the column profile, and roughly three values sampled *independently per
      column and shuffled*, so what is transmitted never reassembles into a complete
      transaction. Bias sampling toward values whose tokens are common across the
      file, so the least identifying examples are the ones sent. This narrows the
      exception rather than closing it -- see the decisions log: layer A needs some
      real values, and pretending otherwise would be dishonest in the DPIA.
- [ ] Mask word tokens in layer B slot-inference samples, where the question is purely
      structural and masking costs nothing. Explicitly not applicable to layer A.
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
      `sample-data/` (added 2026-09-09). Expected mappings landed 2026-09-09 as
      `api/tests/test_fixtures.py`: all five parse, asserted on row count and first
      and last transaction, plus a no-rows-lost invariant, running in CI via pytest.
      The headerless `hsbc.csv` row loss is fixed by `has_header` on `ColumnMapping`.
      Still to do: run real model inference against those expected mappings and
      score it, rather than only pinning the parser.
- [ ] Observability: structured logs and error alerting

## 6. Product
- [ ] Analytics (PostHog or similar), landing copy, changelog
- [ ] Get five real users and record what changed as a result

## Decisions log
- 2026-09-09: Split column inference into two layers. Layer A asks which column
  *contains* a fact and whether it holds the whole value (`exact`) or part of one
  (`embedded`); layer B asks where inside a composite column the fact sits. These were
  conflated in `ColumnMapping`, which is why the problem felt unbounded. Monzo answers
  A and skips B entirely (`Name` is the payee and nothing else); NatWest answers A
  weakly (`Description` carries payee, location, reference, card and date) and needs B.
- 2026-09-09: Governing rule for model use in this milestone -- ask about patterns,
  never about values. Every model output is a column label, a slot index, or a member
  of a closed enum, so code can validate it before applying it. Cost becomes
  O(distinct patterns) rather than O(rows), and a hallucination degrades into a
  validation failure instead of a corrupted transaction.
- 2026-09-09: Masking is self-defeating for semantic-role inference, so layer A will
  send some real values. Replacing `TESCO` with a placeholder destroys the only
  evidence that a column holds a payee; structure tells you a column is atomic and
  name-shaped but not whether that name is a merchant or the account holder. Header
  names carry most of it, but HSBC has no header row at all and real banks ship
  `Narrative1`. Rather than pretend a masked middle ground exists, the exposure is
  narrowed instead: decorrelated per-column sampling, so no complete transaction is
  ever transmitted. Masking still applies to layer B, where the question is structural.
- 2026-09-09: `ColumnMapping` addresses columns by pandas label -- a name when
  `has_header` is true, a 0-based index as a string when it is false -- rather than
  adding a parallel set of `*_index` fields. One set of fields, one source of truth,
  and it mirrors how pandas itself labels columns. Closes the silent row loss on
  headerless CSVs (`hsbc.csv`).
- 2026-09-09: Parked the LLM regex-inference spike for description parsing. It sent six raw sample descriptions to Gemini to get parsing regexes back, was never wired into a response, and broke on CSVs with fewer than six distinct shapes. Removed from `main.py`; the tested `shape()` anonymiser is kept. Revisit the approach (likely: inspect real samples per shape by hand first) under milestone 1.
- 2026-09-09: Stay on the Gemini free tier during development. Real bank statements are not uploaded until the provider decision in milestone 3 is made.
- 2026-09-09: Frontend stack: Vite + React SPA with TanStack Query for server state. Next.js rejected for this project because the app is a static bundle talking to a Python API, so SSR buys nothing and a Next.js host would hide the S3 + CloudFront Terraform work that milestone 4 exists to demonstrate. Next.js goes to the second project, where SSR and a TypeScript backend actually apply. TanStack Query owns request state (in-flight, error, retry, cache) so hooks stop hand-rolling it; the cache earns its keep in milestone 2 when imports and transactions become persisted server state.
- 2026-09-09: Keep Python and FastAPI for the API. A TypeScript backend will be a separate project.
- 2026-09-09: AWS with Terraform for deployment. Vercel rejected because it hides the IaC work. GCP rejected on job-market grounds.
- 2026-09-09: Build agentically with owner review rather than hand-writing React.
