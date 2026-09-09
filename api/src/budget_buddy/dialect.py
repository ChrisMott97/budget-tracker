"""CSV dialect detection: delimiter, preamble and header row, measured without a model.

These three facts used to come back *from* the layer-A model call, which made them
unusable as inputs to it: profiling a file, or sampling values out of one, requires
knowing how to split it first. Detecting them in code breaks that circle, and removes
three questions from the model that `csv.Sniffer` answers deterministically.

Against `sample-data/`, Sniffer alone gets the delimiter and header row right on all
five fixtures, `hsbc.csv`'s headerless case included, and handles `;` and tab files.
The two places it does not survive contact with real statements are handled here:

- A leading preamble makes it fail outright with "Could not determine delimiter", so
  the preamble is found first, by advancing until a sample sniffs cleanly and then
  until the field count settles.
- `has_header` is a type-comparison heuristic and is the fragile part, so a first row
  carrying a number overrides it: no bank writes an amount into its column names.

Nothing raises. A file that defeats every step falls back to the previous defaults, so
detection can only improve on where the parser already stood.
"""

import csv
from collections import Counter

from pydantic import BaseModel, Field

# Sniffer will otherwise happily pick the colon out of a `Account: 1234` preamble line
# or a space out of a padded descriptor. Real statement delimiters are these four.
CANDIDATE_DELIMITERS = ",;\t|"

# Bank preambles are a handful of account-detail lines, not pages. Bounding the search
# keeps a pathological file from being scanned to its end looking for a header.
MAX_PREAMBLE_ROWS = 10

# Enough rows for Sniffer to see a repeated shape, few enough to stay cheap.
SAMPLE_ROWS = 20


class Dialect(BaseModel):
    """How to split a CSV file, before anything asks what its columns mean."""

    skip_rows: int = Field(
        0, description="Number of rows to skip at the start of the CSV file."
    )
    delimiter: str = Field(",", description="Delimiter used in the CSV file.")
    has_header: bool = Field(
        True,
        description=(
            "True if the first row after skip_rows contains column names rather "
            "than transaction data."
        ),
    )


def sample_from(lines: list[str], skip: int) -> str:
    return "\n".join(lines[skip : skip + SAMPLE_ROWS])


def sniff_delimiter(lines: list[str]) -> tuple[int, str] | None:
    """Find the first offset whose sample sniffs, and the delimiter it yields.

    Preamble detection and delimiter detection are mutually dependent -- counting
    fields needs a delimiter, and sniffing one needs preamble-free lines -- so the
    offset is searched rather than derived.
    """
    for skip in range(min(MAX_PREAMBLE_ROWS, len(lines)) + 1):
        sample = sample_from(lines, skip)
        if not sample.strip():
            continue
        try:
            dialect = csv.Sniffer().sniff(sample, delimiters=CANDIDATE_DELIMITERS)
        except csv.Error:
            continue
        return skip, dialect.delimiter
    return None


def skip_to_consistent_rows(lines: list[str], skip: int, delimiter: str) -> int:
    """Advance past leading rows whose field count differs from the file's own.

    The sniff above can succeed while still sitting on a preamble line, because a
    sample starting mid-preamble may contain enough of the table below it to look
    delimited. The modal field count is what the table actually is; anything above it
    with a different width is not part of it.
    """
    rows = list(csv.reader(lines[skip : skip + SAMPLE_ROWS], delimiter=delimiter))
    counts = [len(row) for row in rows if row]
    if not counts:
        return skip

    tally = Counter(counts)
    # Ties break toward the wider row: a two-line preamble and a three-column table
    # can tie, and the table is the one with more fields.
    modal = min(tally.items(), key=lambda item: (-item[1], -item[0]))[0]

    advance = 0
    for row in rows:
        if len(row) == modal:
            break
        advance += 1
    return skip + advance


def looks_numeric(cell: str) -> bool:
    try:
        float(cell.strip().replace(",", ""))
    except ValueError:
        return False
    return True


def first_row_carries_a_number(sample: str, delimiter: str) -> bool:
    """Whether the first row holds a number, which makes it data rather than names.

    A fact about the file rather than a guess about it: no bank writes an amount into
    its column names. This is what `hsbc.csv` needs, and it is the half of the header
    decision that does not depend on Sniffer's heuristic.
    """
    rows = list(csv.reader(sample.splitlines(), delimiter=delimiter))
    return bool(rows) and any(looks_numeric(cell) for cell in rows[0])


def detect_header(sample: str, delimiter: str) -> bool:
    """Decide whether the first row of the sample is column names.

    The override runs first and only ever answers "no"; Sniffer's type comparison
    decides the rest, and a sample it cannot read falls back to the previous default
    of assuming a header.
    """
    if first_row_carries_a_number(sample, delimiter):
        return False
    try:
        return csv.Sniffer().has_header(sample)
    except csv.Error:
        return True


def detect_dialect(csv_text: str) -> Dialect:
    lines = csv_text.splitlines()
    sniffed = sniff_delimiter(lines)
    if sniffed is None:
        # Only the numeric override applies here. `Sniffer.has_header` re-sniffs the
        # sample itself, unrestricted, so on a file this function has already failed
        # to read it guesses a delimiter -- a space, say -- and answers from it.
        # A headerless single-column file is still caught by its first row's number.
        return Dialect(
            has_header=not first_row_carries_a_number(sample_from(lines, 0), ",")
        )

    skip, delimiter = sniffed
    skip = skip_to_consistent_rows(lines, skip, delimiter)
    return Dialect(
        skip_rows=skip,
        delimiter=delimiter,
        has_header=detect_header(sample_from(lines, skip), delimiter),
    )
