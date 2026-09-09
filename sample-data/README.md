# Sample bank statement CSVs

Synthetic fixtures for development, tests and LLM evals. Every name, account
number, reference and amount here is invented. **Real statements must never be
committed** — `real-data/` is gitignored for that reason.

The formats mirror real exports, because the format is the thing under test:
column inference, date parsing, sign conventions and description structure.

| File | Shape | What it exercises |
| --- | --- | --- |
| `natwest.csv` | `Date,Type,Description,Value,Balance,Account Name,Account Number` | Descriptions that are themselves comma-separated sub-fields inside a quoted cell, so naive splitting breaks. A running `Balance` that reconciles. Transaction-type codes (`POS`, `D/D`, `DPC`, `BAC`, `S/O`, `CHG`). Dates as `25 Aug 2026`. Rows newest-first. |
| `amex.csv` | `Date,Description,Amount` | The opposite sign convention: spending is **positive**, card payments negative. Fixed-width descriptions where the merchant is padded to 24 characters before the location. `DD/MM/YYYY` dates. No trailing newline. |
| `monzo.csv` | 16 columns | Two date-ish columns (`Date` and `Time`) and two description-ish ones (`Name` and `Description`), so column inference has to choose. An emoji column, a mostly-empty `Notes` column, and `Local amount`/`Local currency` differing from `Amount` on a foreign transaction. |
| `hsbc.csv` | Three columns, **no header row** | The hardest column-inference case: column identity is positional only. Descriptions carry a transaction-type prefix (`)))` contactless, `VIS`, `DD`, `SO`, `BP`, `CR`, `ATM`) and are quoted and right-padded to 34 characters. Oldest-first, the opposite order to `natwest.csv`. No balance column. |
| `starling.csv` | `Date,Counter Party,Reference,Type,Amount (GBP),Balance (GBP),Spending Category,Notes` | Counterparty and reference already split into their own columns, plus a bank-assigned category. Useful as the target shape for the extraction work in roadmap milestone 1, and as a case where the amount header carries a currency suffix. |

Description structure in `natwest.csv`, for reference:

- `POS` — `<card last 4> <DDMMMYY>[ C] , <MERCHANT> [, <EXTRA>] , <LOCATION> <COUNTRY>`
- `DPC` — `<NAME> , <REF> , TPP <BANK>, FP <DD/MM/YY HH> , <long ref>`
- `BAC` — `<PAYER> , <REFERENCE> , FP <DD/MM/YY HHMM> , <long ref>`
- `D/D`, `S/O`, `CHG` — a plain unquoted merchant string

## Expected mappings

Every file here has a known-good `ColumnMapping` in `api/tests/test_fixtures.py`,
asserted against its row count and its first and last transaction. Those tests
run in CI and hit no network: they pin the parser, not the model.

## Headerless files: `hsbc.csv`

Closed 2026-09-09. `ColumnMapping` carries a `has_header` flag; when it is false
the `*_column` fields hold 0-based column indices as strings (`"0"`) and
`parse_transactions` reads with `header=None`. Previously `pd.read_csv` promoted
the first data row to a header and `hsbc.csv` parsed as 24 rows instead of 25,
losing the oldest transaction with no error. It now parses as all **25 rows**.

It stays the positional-inference fixture: it is the only file here where column
identity is not recoverable from a header, so it is where a wrong inference is
most likely to lose a real user's data quietly.

Still open: nothing checks that the *model* sets `has_header` correctly for it.
That needs the inference eval in ROADMAP milestone 5.

## Regenerating or extending

These are checked-in static files, edited by hand. If you add rows to
`natwest.csv` or `starling.csv`, recompute the balance column so it still
reconciles — a fixture with a broken running balance will quietly invalidate any
test that checks it.
