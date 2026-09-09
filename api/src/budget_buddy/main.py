import datetime
import io
import re
from functools import lru_cache
from typing import Any, Literal

import pandas as pd
from fastapi import FastAPI, HTTPException, UploadFile
from google import genai
from pydantic import BaseModel, Field, model_validator

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

Purity = Literal["exact", "embedded", "absent"]


class FieldSource(BaseModel):
    """Where one fact lives in the CSV, and whether that column holds only it.

    The question is not "is this column the payee" but "does this column *contain*
    the payee", which is the only form every bank can answer: Monzo keeps the payee
    in a column of its own, NatWest buries it in a composite descriptor alongside a
    location and a reference, and Amex ships no category at all.
    """

    column: str | None = Field(
        None,
        description=(
            f"Column containing this fact. {COLUMN_HINT} "
            "Null when the file does not carry the fact."
        ),
    )
    purity: Purity = Field(
        "absent",
        description=(
            "exact: the column holds this fact and nothing else, so its value can be "
            "taken as-is. embedded: the fact is only one part of a larger composite "
            "value in that column. absent: the file does not carry this fact."
        ),
    )

    @model_validator(mode="after")
    def reconcile_column_and_purity(self) -> "FieldSource":
        """Stop the two fields contradicting each other.

        The model emits column and purity independently, so it can pair a real column
        with `absent` or a confident purity with no column. Normalising both directions
        here means callers may test either field alone, and a half-answer degrades into
        a clean "absent" rather than a surprise further down.
        """
        if not self.column:
            self.column = None
            self.purity = "absent"
        elif self.purity == "absent":
            self.column = None
        return self


class FieldMap(BaseModel):
    """The fixed fact list layer A answers, one FieldSource per fact.

    Every fact defaults to absent, so a partial response from the model still
    validates and fails later at the point of use, naming the fact that is missing.
    """

    date: FieldSource = Field(default_factory=FieldSource)
    amount: FieldSource = Field(
        default_factory=FieldSource,
        description="The signed value of the transaction, not the running balance.",
    )
    balance: FieldSource = Field(
        default_factory=FieldSource,
        description="The running account balance after the transaction.",
    )
    payee: FieldSource = Field(
        default_factory=FieldSource,
        description=(
            "The counterparty: the merchant, person or organisation paid or paid by."
        ),
    )
    reference: FieldSource = Field(
        default_factory=FieldSource,
        description=(
            "A payment reference, mandate or transaction id attached to the payment."
        ),
    )
    category: FieldSource = Field(
        default_factory=FieldSource,
        description="A spending category assigned by the bank, not one you infer.",
    )
    txn_type: FieldSource = Field(
        default_factory=FieldSource,
        description=(
            'Payment method or scheme, e.g. "Direct Debit", "POS", "Faster Payment".'
        ),
    )
    currency: FieldSource = Field(default_factory=FieldSource)
    notes: FieldSource = Field(
        default_factory=FieldSource,
        description="Free-text notes added by the customer.",
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
    date_format: str = Field(
        "%Y-%m-%d",
        description="Python strptime format string for parsing dates in the date column.",
    )
    amount_separator: Literal[".", ","] = Field(
        ".", description="Character used as the decimal separator in the amount column."
    )
    fields: FieldMap = Field(
        default_factory=FieldMap,
        description="Which column carries each fact, and how purely it carries it.",
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


def _required_everywhere(node: Any) -> Any:
    if isinstance(node, dict):
        out = {key: _required_everywhere(value) for key, value in node.items()}
        if isinstance(out.get("properties"), dict):
            out["required"] = sorted(out["properties"])
        return out
    if isinstance(node, list):
        return [_required_everywhere(item) for item in node]
    return node


def response_schema() -> dict[str, Any]:
    """The mapping schema with every property marked required.

    Pydantic omits `required` for any field carrying a default, so the generated
    schema demands nothing -- and against the nested field map the model takes that
    option, returning an empty object and leaving all nine facts absent. The defaults
    exist so a *partial* answer degrades into `absent`, not so the question can be
    skipped, so the schema the model is handed asks for every fact and both halves of
    each one. `column` stays nullable, which turns "no such column" into something the
    model must state rather than something it can omit.
    """
    return _required_everywhere(ColumnMapping.model_json_schema())


def infer_column_mapping(csv_text: str, client: genai.Client) -> ColumnMapping:
    head = "\n".join(csv_text.splitlines()[:10])
    prompt = (
        "This is the start of a CSV file of bank transactions. Do not parse or "
        "return any transaction data. Describe where each fact lives, as JSON.\n\n"
        "For every field, answer with the column that carries it and how purely "
        "that column carries it:\n"
        "- exact: the column holds that fact and nothing else.\n"
        "- embedded: the fact is one part of a larger composite value, such as a "
        "payee inside a descriptor that also carries a location and a reference.\n"
        "- absent: the file does not carry the fact at all. Use a null column.\n\n"
        "Two facts may name the same column when both are embedded in it. Prefer a "
        "dedicated column over an embedded one when the file offers both.\n\n"
        "The first lines of the CSV file are:\n\n"
    )
    interaction = client.interactions.create(
        model="gemini-flash-lite-latest",
        input=prompt + head,
        response_format={
            "type": "text",
            "mime_type": "application/json",
            "schema": response_schema(),
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


def required_column(source: FieldSource, fact: str, has_header: bool) -> str | int:
    """Resolve a fact the parser cannot do without into a pandas column label."""
    if source.column is None:
        raise HTTPException(
            422, f"Column mapping found no column for the required field '{fact}'."
        )
    return column_label(source.column, has_header)


def parse_transactions(
    csv_text: str, column_mapping: ColumnMapping
) -> list[Transaction]:
    has_header = column_mapping.has_header
    fields = column_mapping.fields
    date = required_column(fields.date, "date", has_header)
    amount = required_column(fields.amount, "amount", has_header)
    # The payee column is the description source at either purity. When it is `exact`
    # the value is already the whole answer; when it is `embedded` the full composite
    # passes through unchanged until layer B can split it into slots.
    description = required_column(fields.payee, "payee", has_header)

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
