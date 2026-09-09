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
- [x] **Layer A -- field-presence map** 2026-09-09. The flat `*_column` fields on
      `ColumnMapping` are gone, replaced by a per-fact `FieldSource {column, purity}`
      where purity is `exact` / `embedded` / `absent`, over a fixed fact list: date,
      amount, balance, payee, reference, category, txn_type, currency, notes. `exact`
      means take the column as-is; `embedded` is the only thing that will trigger
      layer B. The question is no longer "is this column the payee" but "does this
      column *contain* the payee", which is what the fixtures actually demand: Monzo's
      payee is (`Name`, exact), NatWest's is (`Description`, embedded), Amex's category
      is absent. Those answers are now pinned per fixture in
      `api/tests/test_fixtures.py`, so the sample set doubles as the layer-A eval
      target. `parse_transactions` takes its description from `payee` at either purity
      -- an `embedded` value passes through whole until layer B can split it -- so no
      fixture output changed. `FieldSource` reconciles column against purity in both
      directions, which is where an incoherent model answer degrades into `absent`
      instead of a corrupted mapping; a fact the parser requires that ends up absent is
      a 422 naming the fact. `response_schema()` marks every property required on the
      wire -- see the decisions log for why the nested schema needs that and the flat
      one did not.
- [x] **Detect the dialect in code** 2026-09-09, no model involved. `delimiter`,
      `has_header` and `skip_rows` are measured by `api/src/budget_buddy/dialect.py`
      (`csv.Sniffer`, stdlib, no new dependency) and no longer appear in the schema
      handed to the model, which now answers only `date_format`, `amount_separator`,
      `fields` and `confidence` -- `ColumnMapping` is the measured `Dialect` plus that
      `InferredMapping`. Sniffer alone is right on all five fixtures; the two shapes it
      does not survive are handled around it. A leading preamble makes it fail outright
      ("Could not determine delimiter"), so the offset is searched -- advance until a
      sample sniffs, then until the field count settles on its mode. And `has_header`
      is a type-comparison heuristic, so a first row containing a number overrides it
      to "data": that is a fact about the file rather than a guess, and it is what
      `hsbc.csv` needs. Every step falls back to the previous defaults, so detection
      can only improve on where the parser stood. `test_fixtures.py` now asserts
      detection against the dialect already pinned per fixture, so the sample set is
      the eval for this too.
- [x] **Wire the column profiler into the layer-A prompt** 2026-09-09.
      `infer_column_mapping` now builds a raw frame via `profile.read_raw_frame`,
      runs `profile_columns` and `sample_column_values` over it, and hands the model
      a JSON profile (per-column stats, containments, and the samples below) instead
      of the CSV head. The prompt explains how to read cardinality, case, token
      count and containment. Landed together with the milestone 3 narrowing below,
      as planned, since both rewrite the same prompt.
- [x] **Column profiler** 2026-09-09, no model involved: per column, cardinality
      ratio, mean token count, mean length, case profile with its consistency
      fraction, fill rate, and cross-column token containment. Landed as
      `api/src/budget_buddy/profile.py` with `api/tests/test_profile.py` pinning the
      measurements below against the fixtures. Not yet wired into `main.py` -- see the
      wiring item above.
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
- [x] **Bucket refinement** 2026-09-09. `shape()` collapsed word runs, so the
      dominant bucket was a bare `W+` on three of five fixtures (14/23 Amex,
      16/25 HSBC, 12/15 Monzo) -- one slot over the whole string, useless for slot
      assignment. `shapes.bucket_by_refined_shape` splits it, pure computation:
      structural tokens are re-tagged `PFX` and only the payee run stays `W+`.
      Two signals, each earned against the fixtures. The head is matched against a
      curated `BANK_PREFIX_VOCAB` (`CR`, `DD`, `VIS`, `BP`, `SO`, `ATM`, `)))`,
      plus common UK siblings) and *never* against frequency -- the caveat that a
      monthly payment to a named individual recurs just as reliably is honoured by
      never letting frequency touch the leading run. The tail is matched against a
      per-bucket token-frequency table indexed *from the end* (a trailing location
      sits a fixed offset from the end while the payee's length varies), gated on
      the bucket having >= 3 distinct leading tokens so `ALEX HOLLOWAY RENT
      <month>` x N is left whole rather than fragmented. Result: HSBC's `W+`
      bucket collapses to `PFX W+` (19 rows, including the `)))` contactless
      rows), Amex's 16-row `W+` drops to 7 with a `W+ PFX` sibling that isolates
      the city. Monzo's `Description` stays put -- it is short and low-structure,
      and Monzo's payee is the `exact` `Name` column anyway. Landed as
      `api/src/budget_buddy/shapes.py` with `tokenise`/`classify`/`shape` moved
      out of `main.py` (closing the duplicated tokeniser flagged in `profile.py`);
      pinned in `api/tests/test_shapes.py`. Not wired into the endpoint -- layer B
      consumes it next.
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
- [x] Narrow the column-mapping exception 2026-09-09. The raw CSV head is gone;
      `infer_column_mapping` sends headers, the column profile, and up to three
      sample values per column. `profile.sample_column_values` picks those values by
      the mean file-wide frequency of their tokens, so a once-only merchant name
      loses to a `DIRECT DEBIT` that identifies nobody, and returns them `sorted()`
      per column -- decorrelated from row order and independent across columns, so no
      complete transaction can be reassembled. Deterministic, not a random shuffle
      (decisions log). This narrows the exception rather than closing it: layer A
      still needs some real values, and pretending otherwise would be dishonest in
      the DPIA.
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
      First live layer-A run, 2026-09-09, gemini-flash-lite against four fixtures, by
      hand rather than in CI: every fact the parser needs was correct on all four, and
      all three cases the layer-A design was built around came back right -- Monzo
      payee (`Name`, exact), NatWest payee (`Description`, embedded), Amex category
      absent. Two divergences from the pinned expectations, both harmless and both left
      unchanged so the eval keeps reporting them: Starling `currency` came back as
      (`Amount (GBP)`, embedded) when the currency is in the header label and not in the
      values, and Monzo `reference` as (`Description`, exact) for what is really a raw
      descriptor. Neither is wired into parsing yet.
- [ ] Observability: structured logs and error alerting

## 6. Product
- [ ] Analytics (PostHog or similar), landing copy, changelog
- [ ] Get five real users and record what changed as a result

## Decisions log
- 2026-09-09: Bucket refinement splits the head against a vocabulary and the tail
  against frequency, not one rule for both. "Recurs at a position, therefore
  structural" is the roadmap's proposed heuristic, but it fails at the head: a
  monthly payment to `ALEX HOLLOWAY` puts `HOLLOWAY` at the same position on every
  row just as `CR` does. So the leading run is matched only against
  `BANK_PREFIX_VOCAB` (small, curated, non-personal), and frequency -- indexed
  from the *end*, where locations and scheme suffixes sit at a fixed offset while
  the payee varies in length -- is allowed only past the head, and only for a
  bucket with >= 3 distinct leading tokens so a one-payee-repeated bucket is never
  fragmented. `RECUR_FRACTION` (0.4) and `RECUR_MIN_ROWS` (3) are first-cut; layer
  B is the first real consumer and will show whether they hold.
- 2026-09-09: `tokenise`/`classify`/`shape` moved from `main.py` to a new
  `shapes.py`, as the `profile.py` comment anticipated ("the shared tokeniser
  moves to its own module when bucket refinement lands"). `main` -> `shapes` and
  `profile` -> `shapes` both resolve without the cycle that forced the duplicated
  `TOKEN_RE`; `shape()` output is unchanged (`_collapse_runs` is shared with
  `refined_shape`, and the moved tests still pin it).
- 2026-09-09: The column profiler was wired into the layer-A prompt and the raw CSV
  head it replaced was dropped in the same diff, as the milestone-1 wiring item
  anticipated -- both rewrite the same prompt, so splitting them would have meant two
  churny passes over it. Sample-value selection is deterministic (top-k by token
  commonality, then `sorted()`) rather than a random shuffle: decorrelation only
  needs the emitted order to carry no row information, and a reproducible profile is
  worth more than a shuffled one -- the same reasoning as the head-slice and sorted
  tie-breaks already in `profile.py`.
- 2026-09-09: Dialect detection landed as its own diff, ahead of the prompt rewrite it
  exists to unblock, rather than alongside it as this file originally proposed. The two
  do share a prompt, but a mis-sniffed delimiter and a badly narrowed prompt would
  otherwise arrive as one indistinguishable failure -- the same reasoning that split
  layer A from the profiler. The model is no longer asked anything `csv.Sniffer` can
  measure, on the general principle already governing this milestone: ask the model
  about patterns, never about facts code can establish.
- 2026-09-09: The schema handed to the model marks every property required, added after
  the first live run of the nested field map came back with all nine facts `absent`.
  Pydantic omits `required` for any field carrying a default, so the generated schema
  demanded nothing and Gemini legitimately returned an empty object -- a flat schema of
  scalars survived that, a nested one does not. The defaults stay in the Python model,
  where their job is to degrade a *partial* answer into `absent`; `response_schema()`
  re-imposes the requirement only on the wire, and `column` stays nullable so "this file
  has no such column" is something the model states rather than omits.
- 2026-09-09: Layer A ships its field map before the column profiler is wired into the
  prompt, even though layer A was meant to be the profiler's first consumer. Profiling
  a file requires its delimiter, header row and skip count, and those are part of what
  the model currently infers, so consuming a profile means detecting the dialect in
  code first. Splitting keeps the field-map diff reviewable and stops a mis-sniffed
  delimiter and a wrong field map arriving as one indistinguishable failure.
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
