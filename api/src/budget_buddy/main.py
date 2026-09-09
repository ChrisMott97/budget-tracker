import datetime
import io
import re
from functools import lru_cache
from typing import Literal

import pandas as pd
from fastapi import FastAPI, HTTPException, UploadFile
from google import genai
from pydantic import BaseModel, Field

app = FastAPI()


@lru_cache
def get_client() -> genai.Client:
    return genai.Client()


class Transaction(BaseModel):
    date: datetime.date
    description: str
    amount: float


COLUMN_HINT = (
    "Column name when has_header is true, otherwise the 0-based column index "
    'as a string, e.g. "0".'
)


class ColumnMapping(BaseModel):
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
    date_column: str = Field(
        "date", description=f"Column containing transaction dates. {COLUMN_HINT}"
    )
    date_format: str = Field(
        "%Y-%m-%d",
        description="Python strptime format string for parsing dates in the date column.",
    )
    description_column: str = Field(
        "description",
        description=f"Column containing transaction descriptions. {COLUMN_HINT}",
    )
    amount_column: str = Field(
        "amount", description=f"Column containing transaction amounts. {COLUMN_HINT}"
    )
    amount_separator: Literal[".", ","] = Field(
        ".", description="Character used as the decimal separator in the amount column."
    )
    confidence: float = Field(
        0.8, description="Confidence that the date format is correct."
    )


def decode_csv(raw: bytes) -> tuple[str, str]:
    for enc in ["utf-8-sig", "cp1252", "latin-1"]:
        try:
            return raw.decode(enc), enc
        except UnicodeDecodeError:
            continue
    raise ValueError("Unable to decode CSV file with available encodings.")


def infer_column_mapping(csv_text: str, client: genai.Client) -> ColumnMapping:
    head = "\n".join(csv_text.splitlines()[:10])
    prompt = "This is the start of a CSV file which contains bank transactions. Do not parse the transactions, determine the column mapping and return the mapping in JSON format. The first lines of the CSV file are:\n\n"
    interaction = client.interactions.create(
        model="gemini-flash-lite-latest",
        input=prompt + head,
        response_format={
            "type": "text",
            "mime_type": "application/json",
            "schema": ColumnMapping.model_json_schema(),
        },
    )

    if not interaction.output_text:
        raise HTTPException(502, "Model returned no output")

    return ColumnMapping.model_validate_json(interaction.output_text)


def column_label(column: str, has_header: bool) -> str | int:
    """Resolve a mapping value to the label pandas will give that column.

    pandas labels columns by name when the file has a header row and by 0-based
    integer position when it does not, so the mapping carries whichever applies.
    """
    if has_header:
        return column
    try:
        return int(column)
    except ValueError:
        raise HTTPException(
            422,
            "Column mapping addressed a headerless CSV by name; a 0-based column index is required.",
        ) from None


def parse_transactions(
    csv_text: str, column_mapping: ColumnMapping
) -> list[Transaction]:
    has_header = column_mapping.has_header
    date = column_label(column_mapping.date_column, has_header)
    amount = column_label(column_mapping.amount_column, has_header)
    description = column_label(column_mapping.description_column, has_header)

    df = pd.read_csv(
        io.StringIO(csv_text),
        header=0 if has_header else None,
        skiprows=column_mapping.skip_rows,
        delimiter=column_mapping.delimiter,
        parse_dates=[date],
        date_format=column_mapping.date_format,
        decimal=column_mapping.amount_separator,
        usecols=[date, amount, description],
    )

    df = df.rename(columns={date: "date", amount: "amount", description: "description"})
    # Some exports right-pad descriptions to a fixed width; that padding is a
    # formatting artefact, not data, and would fragment shape() buckets later.
    df["description"] = df["description"].str.strip()
    df = df.where(pd.notna(df), None)
    return [Transaction.model_validate(row) for row in df.to_dict(orient="records")]


TOKEN_RE = re.compile(r"(?P<comma>\s*,\s*)|(?P<space>\s+)|(?P<word>[^\s,]+)")

# TODO: extend to other date formats
DATE_RE = re.compile(
    r"""^(
    \d{1,2}[A-Z]{3}\d{2,4}          # 12MAR25
  | \d{1,2}[/-]\d{1,2}[/-]\d{2,4}   # 12/03/25
  | \d{4}-\d{2}-\d{2}               # 2025-03-12
)$""",
    re.VERBOSE,
)

WORD_RE = re.compile(r"[*]?[^\W\d_][\w'&.\-*]*", re.UNICODE)


def classify(tok: str) -> str:
    if DATE_RE.match(tok):
        return "DATE"
    if re.fullmatch(r"\d+", tok):
        return f"N{len(tok)}" if len(tok) <= 6 else "N+"
    if tok == "&":
        return "AMP"
    if WORD_RE.fullmatch(tok):
        return "W"
    return "X"


def tokenise(desc: str) -> list[tuple[str, str, int, int]]:
    """Returns [(kind, text, start, end)] covering the whole string."""
    out = []
    for m in TOKEN_RE.finditer(desc):
        kind = m.lastgroup
        out.append((kind, m.group(), m.start(), m.end()))
    return out


def shape(desc: str) -> str:
    toks = [
        (classify(t), t) for k, t, _, _ in tokenise(desc) if k == "word" or k == "comma"
    ]
    toks = [("COMMA", t) if t.strip() == "," else (c, t) for c, t in toks]

    parts, run, i = [], False, 0
    while i < len(toks):
        cls, _ = toks[i]

        if cls == "COMMA":
            parts.append(",")
            run = False

        elif cls == "AMP":
            nxt = toks[i + 1][0] if i + 1 < len(toks) else None
            if run and nxt == "W":
                i += 2  # swallow the & and the word after it
                continue
            run = False
            parts.append("X")  # dangling &, treat as junk

        elif cls == "W":
            if not run:
                parts.append("W+")
                run = True

        else:
            parts.append(cls)
            run = False

        i += 1
    return " ".join(parts)


@app.post("/transactions")
def csv_to_transactions(file: UploadFile) -> list[Transaction]:
    text, _ = decode_csv(file.file.read())

    client = get_client()
    column_mapping = infer_column_mapping(text, client)

    rows = parse_transactions(text, column_mapping)

    # Next (ROADMAP milestone 1): use shape() to bucket descriptions and pull
    # counterparty/reference out of them without sending raw text to the model.
    return rows
