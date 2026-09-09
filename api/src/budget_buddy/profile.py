"""Column profiling: facts about each CSV column, measured without a model.

Layer A has to decide whether a column *contains* a fact, and it cannot lean on
header names alone -- `hsbc.csv` has no header row and real banks ship columns
called `Narrative1`. This module derives the evidence outright so the model is
later asked to label columns it has been handed statistics for.

What the measurements do and do not separate, against `sample-data/`:

- Cardinality ratio separates enum and constant columns from per-transaction
  ones: NatWest `Type` 0.17, Starling `Spending Category` 0.50, NatWest
  `Account Name` 0.03. It does *not* separate a clean payee column from a raw
  descriptor -- Monzo `Name` and NatWest `Description` are both ~1.00.
- Mean token count and case profile make that second distinction: Monzo `Name`
  is 1.6 tokens and Mixed case, NatWest `Description` is 6.9 tokens and 97%
  UPPER.
- Containment computes the "does this column include that column's data"
  relationship directly: Monzo `Name` is a subset of `Description` on 80% of
  rows. It is deliberately silent when the evidence is weak -- Starling
  `Counter Party` and `Reference` overlap on only half the rows and are not
  reported.
"""

import io
import itertools
import re
from collections import Counter
from typing import Literal

import pandas as pd
from pydantic import BaseModel, Field

# Matches the `word` alternative of main.TOKEN_RE. Duplicated rather than
# imported because main.py constructs the FastAPI app and the dependency will
# eventually run main -> profile; the shared tokeniser moves to its own module
# when bucket refinement lands.
TOKEN_RE = re.compile(r"[^\s,]+")

# Monzo `Name` is contained in `Description` on 0.80 of rows and is the signal we
# want. Starling `Counter Party` in `Reference` reaches only 0.50 and Monzo
# `Address` in `Description` 0.67; both are noise, so the bar sits above them.
CONTAINMENT_THRESHOLD = 0.75

# Containment is O(columns^2 * rows) of set work. A deterministic head slice
# keeps a profile reproducible where a random sample would not.
CONTAINMENT_SAMPLE_ROWS = 200

# How many example values per column layer A is handed. Enough for the model to
# tell a merchant from an account holder; few enough that one column's samples
# plus the profile never amount to a transaction.
PROMPT_SAMPLE_SIZE = 3

CaseProfile = Literal["UPPER", "lower", "Mixed", "none"]


class ColumnProfile(BaseModel):
    """Measured facts about one column. No raw values are carried."""

    label: str = Field(
        description=(
            "Column name when the CSV has a header, otherwise the 0-based column "
            'index as a string, e.g. "0".'
        )
    )
    fill_rate: float = Field(
        description="Fraction of rows where the column is non-empty."
    )
    cardinality_ratio: float = Field(
        description=(
            "Distinct non-empty values divided by non-empty values. Near 0 marks a "
            "constant, low values mark an enum, near 1 marks per-transaction data."
        )
    )
    mean_token_count: float = Field(
        description="Mean whitespace- and comma-separated token count of non-empty values."
    )
    mean_length: float = Field(description="Mean character length of non-empty values.")
    case_profile: CaseProfile = Field(
        description="The most common letter-case class across non-empty values."
    )
    case_consistency: float = Field(
        description="Fraction of non-empty values matching case_profile."
    )


class Containment(BaseModel):
    """Evidence that one column's values sit inside another's."""

    contained: str = Field(
        description="Label of the column whose tokens appear inside the other."
    )
    container: str = Field(
        description="Label of the wider column carrying those tokens."
    )
    fraction: float = Field(description="Fraction of rows where the containment holds.")


class FileProfile(BaseModel):
    row_count: int
    columns: list[ColumnProfile]
    containments: list[Containment]


def read_raw_frame(
    csv_text: str,
    *,
    skip_rows: int = 0,
    delimiter: str = ",",
    has_header: bool = True,
) -> pd.DataFrame:
    """Read every column as text, before any type coercion.

    Profiling has to see what the file actually holds, so nothing is parsed as a
    date or a number and `keep_default_na` is off -- pandas would otherwise turn
    an empty cell and the literal string "NA" into the same NaN, which is exactly
    the distinction fill rate measures.
    """
    frame = pd.read_csv(
        io.StringIO(csv_text),
        header=0 if has_header else None,
        skiprows=skip_rows,
        delimiter=delimiter,
        dtype=str,
        keep_default_na=False,
    )
    frame.columns = [str(label) for label in frame.columns]
    return frame


def case_of(value: str) -> CaseProfile:
    letters = [char for char in value if char.isalpha()]
    if not letters:
        return "none"
    if all(char.isupper() for char in letters):
        return "UPPER"
    if all(char.islower() for char in letters):
        return "lower"
    return "Mixed"


def tokens(value: str) -> list[str]:
    return TOKEN_RE.findall(value)


def profile_column(label: str, values: list[str]) -> ColumnProfile:
    filled = [value for value in values if value]
    if not filled:
        return ColumnProfile(
            label=label,
            fill_rate=0.0,
            cardinality_ratio=0.0,
            mean_token_count=0.0,
            mean_length=0.0,
            case_profile="none",
            case_consistency=0.0,
        )

    count = len(filled)
    cases = Counter(case_of(value) for value in filled)
    # Sorting by (-count, name) rather than Counter.most_common keeps the winner
    # deterministic when two case classes tie, so profiles are reproducible.
    dominant, dominant_count = min(cases.items(), key=lambda item: (-item[1], item[0]))

    return ColumnProfile(
        label=label,
        fill_rate=count / len(values),
        cardinality_ratio=len(set(filled)) / count,
        mean_token_count=sum(len(tokens(value)) for value in filled) / count,
        mean_length=sum(len(value) for value in filled) / count,
        case_profile=dominant,
        case_consistency=dominant_count / count,
    )


def find_containments(
    columns: dict[str, list[str]], profiles: list[ColumnProfile]
) -> list[Containment]:
    """Report each column whose tokens sit inside a wider column's, per row.

    Tokens are upper-cased before comparison so Monzo's `Tesco` matches the
    `TESCO EXPRESS ...` descriptor. Rows where either side is empty are skipped
    rather than counted as a match, so a sparse column cannot look contained by
    being blank.
    """
    token_sets = {
        label: [
            set(map(str.upper, tokens(value)))
            for value in values[:CONTAINMENT_SAMPLE_ROWS]
        ]
        for label, values in columns.items()
    }
    widths = {profile.label: profile.mean_token_count for profile in profiles}

    fractions: dict[tuple[str, str], float] = {}
    for inner, outer in itertools.permutations(columns, 2):
        pairs = [
            (small, large)
            for small, large in zip(token_sets[inner], token_sets[outer])
            if small and large
        ]
        if not pairs:
            continue
        fractions[(inner, outer)] = sum(
            1 for small, large in pairs if small <= large
        ) / len(pairs)

    found = []
    for (inner, outer), fraction in fractions.items():
        if fraction < CONTAINMENT_THRESHOLD:
            continue
        # Columns that contain each other are duplicates of one value, not one
        # value embedded in another: Monzo `Amount` and `Local amount` match both
        # ways. Embedding is asymmetric, so symmetric pairs are dropped.
        if fractions.get((outer, inner), 0.0) >= CONTAINMENT_THRESHOLD:
            continue
        if widths[outer] <= widths[inner]:
            continue
        found.append(Containment(contained=inner, container=outer, fraction=fraction))

    return sorted(
        found, key=lambda item: (-item.fraction, item.contained, item.container)
    )


def raw_columns(frame: pd.DataFrame) -> dict[str, list[str]]:
    """The `{label: [stripped values]}` view every function in this module works from."""
    return {
        str(label): [str(value).strip() for value in frame[label]]
        for label in frame.columns
    }


def profile_columns(frame: pd.DataFrame) -> FileProfile:
    """Profile every column of an all-text frame from `read_raw_frame`."""
    columns = raw_columns(frame)
    profiles = [profile_column(label, values) for label, values in columns.items()]
    return FileProfile(
        row_count=len(frame),
        columns=profiles,
        containments=find_containments(columns, profiles),
    )


def file_token_frequencies(columns: dict[str, list[str]]) -> Counter[str]:
    """Upper-cased token counts across every non-empty cell of every column.

    Upper-casing matches `find_containments`, so `Tesco` and `TESCO` count as one
    token. This is the "how common is this token across the file" table the sample
    selection leans on.
    """
    freq: Counter[str] = Counter()
    for values in columns.values():
        for value in values:
            if value:
                freq.update(token.upper() for token in tokens(value))
    return freq


def sample_column_values(
    columns: dict[str, list[str]], *, size: int = PROMPT_SAMPLE_SIZE
) -> dict[str, list[str]]:
    """Up to `size` example values per column, chosen and ordered to leak the least.

    Layer A genuinely needs some real values -- structure tells you a column is
    name-shaped but not whether the name is a merchant or the account holder (see
    the decisions log). This narrows that exposure two ways:

    - Selection is biased toward values whose tokens recur across the file, so a
      once-only merchant name is passed over in favour of a `PAYMENT` or
      `DIRECT DEBIT` that identifies nobody. A value's score is the mean file
      frequency of its tokens.
    - The returned order is `sorted()` on the value string, decorrelated from row
      order and independent per column, so the samples for two columns carry no
      positional relationship and no transaction row can be reassembled.

    Deterministic throughout: same file in, same samples out.
    """
    freq = file_token_frequencies(columns)

    def score(value: str) -> float:
        value_tokens = [token.upper() for token in tokens(value)]
        if not value_tokens:
            return 0.0
        return sum(freq[token] for token in value_tokens) / len(value_tokens)

    sampled: dict[str, list[str]] = {}
    for label, values in columns.items():
        distinct = sorted({value for value in values if value})
        chosen = sorted(distinct, key=lambda value: (-score(value), value))[:size]
        sampled[label] = sorted(chosen)
    return sampled
