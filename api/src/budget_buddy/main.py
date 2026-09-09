import datetime
import io
import json
from functools import lru_cache
from typing import Any, Literal

import pandas as pd
from fastapi import FastAPI, HTTPException, UploadFile
from google import genai
from pydantic import BaseModel, Field, model_validator

from budget_buddy.dialect import Dialect, detect_dialect
from budget_buddy.profile import (
    profile_columns,
    raw_columns,
    read_raw_frame,
    sample_column_values,
)
from budget_buddy.shapes import mask_words, non_comma_slot_count, refine_with_slots

app = FastAPI()


@lru_cache
def get_client() -> genai.Client:
    return genai.Client()


class Transaction(BaseModel):
    date: datetime.date
    description: str
    amount: float
    # Filled from layer-A `exact` columns, or (reference / txn_type) from a layer-B
    # slot. Optional because every fact is bank-specific: Amex ships none of them.
    balance: float | None = None
    category: str | None = None
    reference: str | None = None
    txn_type: str | None = None
    currency: str | None = None
    # The bank category label or payee string that produced `category`, so the
    # frontend can regroup rows under an edited mapping entry without a re-upload.
    # For an embedded-payee row the description is already the payee (no new raw
    # data); for a bank-category row this is the bank's own label.
    category_source: str | None = None


# The file's header row is measured, not inferred, so which of the two addressing
# schemes applies is stated in the prompt rather than left to the model.
COLUMN_HINT = "Column name, or the 0-based column index as a string, as instructed."

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


class InferredMapping(BaseModel):
    """The half of the mapping a model has to answer, and the whole of its schema.

    The dialect is deliberately not here: `dialect.detect_dialect` measures it from
    the file, so asking the model for it would be asking a question that already has
    an answer -- and one the profiler needs *before* the call can be made.
    """

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


class ColumnMapping(InferredMapping, Dialect):
    """Everything the parser needs: the measured dialect plus the inferred mapping.

    Inheritance rather than composition keeps the field set flat, so the parser and
    the fixtures address `has_header` and `fields` on one object as they always have.
    """


# The facts layer B can lift out of an embedded descriptor column. A subset of the
# layer-A fact list: an amount or a balance never hides inside a payee descriptor.
EMBEDDED_FACTS = ("payee", "date", "reference", "txn_type")

# Optional facts surfaced on `Transaction` when layer A marks their column `exact`.
# `balance` is numeric; the rest are pass-through bank labels coerced to str, so a
# numeric-looking category column cannot break row validation.
OPTIONAL_EXACT_FACTS = ("balance", "category", "reference", "txn_type", "currency")
OPTIONAL_STRING_FACTS = ("category", "reference", "txn_type", "currency")


class SlotAssignment(BaseModel):
    """Which slot of a refined shape holds each embedded fact, as a 0-based index.

    The model emits only integers here, so it cannot substitute a value it invented
    for one the file holds: an out-of-range index is caught and dropped, not applied.
    """

    payee: int | None = Field(
        None, description="Slot index of the counterparty, or null."
    )
    date: int | None = Field(
        None, description="Slot index of the transaction date, or null."
    )
    reference: int | None = Field(
        None, description="Slot index of a payment reference, or null."
    )
    txn_type: int | None = Field(
        None, description="Slot index of the payment method or scheme, or null."
    )


class SlotMap(BaseModel):
    """The model's answer for a batch of shapes: one assignment per shape, in order."""

    assignments: list[SlotAssignment] = Field(
        default_factory=list,
        description="One SlotAssignment per shape, in the order the shapes were given.",
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

    Built from `InferredMapping`, not `ColumnMapping`: the dialect fields are measured
    from the file, so they never reach the wire.
    """
    return _required_everywhere(InferredMapping.model_json_schema())


def profile_prompt_block(csv_text: str, dialect: Dialect) -> str:
    """The anonymised profile layer A reasons over, as pretty JSON.

    Per column: the measured statistics from `profile_columns`, plus up to three
    example values from `sample_column_values` -- sorted, decorrelated from row
    order and chosen for least identifiability, so the block never reassembles
    into a transaction. Replaces the raw CSV head this function used to send.
    """
    frame = read_raw_frame(
        csv_text,
        skip_rows=dialect.skip_rows,
        delimiter=dialect.delimiter,
        has_header=dialect.has_header,
    )
    profile = profile_columns(frame)
    samples = sample_column_values(raw_columns(frame))

    payload = {
        "row_count": profile.row_count,
        "columns": [
            {
                "label": column.label,
                "fill_rate": round(column.fill_rate, 2),
                "cardinality_ratio": round(column.cardinality_ratio, 2),
                "mean_token_count": round(column.mean_token_count, 2),
                "mean_length": round(column.mean_length, 2),
                "case_profile": column.case_profile,
                "case_consistency": round(column.case_consistency, 2),
                "samples": samples[column.label],
            }
            for column in profile.columns
        ],
        "containments": [
            {
                "contained": item.contained,
                "container": item.container,
                "fraction": round(item.fraction, 2),
            }
            for item in profile.containments
        ],
    }
    return json.dumps(payload, indent=2)


def infer_column_mapping(
    csv_text: str, client: genai.Client, dialect: Dialect
) -> ColumnMapping:
    # How to address a column depends on whether the file has a header, and the model
    # no longer decides that, so it has to be told which of the two answers to give.
    addressing = (
        "The file has a header row; name each column by its header, which is the "
        "label field in the profile."
        if dialect.has_header
        else "This file has no header row; identify each column by its 0-based "
        'index as a string, e.g. "0", which is the label field in the profile.'
    )
    prompt = (
        "You are given an anonymised profile of a CSV file of bank transactions, "
        "not the file itself. Do not parse or return any transaction data. Using "
        "the profile, describe where each fact lives, as JSON.\n\n"
        "For every field, answer with the column that carries it and how purely "
        "that column carries it:\n"
        "- exact: the column holds that fact and nothing else.\n"
        "- embedded: the fact is one part of a larger composite value, such as a "
        "payee inside a descriptor that also carries a location and a reference.\n"
        "- absent: the file does not carry the fact at all. Use a null column.\n\n"
        "Two facts may name the same column when both are embedded in it. Prefer a "
        "dedicated column over an embedded one when the file offers both.\n\n"
        "How to read the profile:\n"
        "- cardinality_ratio near 0 is a constant column, low is an enum such as a "
        "txn_type or a bank category, near 1 is per-transaction data.\n"
        "- A low mean_token_count in Mixed or Title case is a bank-cleaned "
        "counterparty; a high token count in UPPER case is a raw descriptor with a "
        "payee, and often a reference and a date, embedded in it.\n"
        "- A containments entry means the contained column's value appears inside "
        "the container column, so that fact is embedded in the container.\n"
        "- samples are a few example values per column, sorted and independent of "
        "row order: they do not line up across columns and are not real rows.\n\n"
        f"{addressing}\n\n"
        "The file profile is:\n\n"
    )
    interaction = client.interactions.create(
        model="gemini-flash-lite-latest",
        input=prompt + profile_prompt_block(csv_text, dialect),
        response_format={
            "type": "text",
            "mime_type": "application/json",
            "schema": response_schema(),
        },
    )

    if not interaction.output_text:
        raise HTTPException(502, "Model returned no output")

    inferred = InferredMapping.model_validate_json(interaction.output_text)
    return ColumnMapping(**dialect.model_dump(), **inferred.model_dump())


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

    core = {date: "date", amount: "amount", description: "description"}
    # Each layer-A `exact` optional fact, mapped to the pandas label of its column.
    # A fact whose column is one of the core three is skipped: it is already read,
    # and a duplicate in `usecols` would raise.
    optional = {
        column_label(source.column, has_header): fact
        for fact in OPTIONAL_EXACT_FACTS
        if (source := getattr(fields, fact)).purity == "exact"
        and source.column is not None
        and column_label(source.column, has_header) not in core
    }

    df = pd.read_csv(
        io.StringIO(csv_text),
        header=0 if has_header else None,
        skiprows=column_mapping.skip_rows,
        delimiter=column_mapping.delimiter,
        parse_dates=[date],
        date_format=column_mapping.date_format,
        decimal=column_mapping.amount_separator,
        usecols=[*core, *optional],
    )

    df = df.rename(columns={**core, **optional})
    # Some exports right-pad descriptions to a fixed width; that padding is a
    # formatting artefact, not data, and would fragment shape() buckets later.
    df["description"] = df["description"].str.strip()
    df = df.where(pd.notna(df), None)
    # Coerce the pass-through label columns to str so a numeric-looking category or
    # reference (which pandas would type as float) still validates as `str | None`.
    for fact in OPTIONAL_STRING_FACTS:
        if fact in df.columns:
            df[fact] = df[fact].map(lambda value: None if value is None else str(value))
    return [Transaction.model_validate(row) for row in df.to_dict(orient="records")]


def embedded_facts_in(fields: FieldMap, column: str) -> list[str]:
    """The `EMBEDDED_FACTS` layer A placed, `embedded`, in this one column.

    Used only to tell layer B which facts to look for -- `payee` is always here
    (an `embedded` payee is what triggers the layer-B call at all), and NatWest's
    descriptor also carries `date` and `reference`.
    """
    return [
        fact
        for fact in EMBEDDED_FACTS
        if (source := getattr(fields, fact)).purity == "embedded"
        and source.column == column
    ]


def _validated_assignment(assignment: SlotAssignment, shape: str) -> SlotAssignment:
    """Drop any slot index that falls outside the shape's slot range.

    The model answers with integers, so a hallucination is an out-of-range index,
    not a fabricated merchant. A bad index degrades that one shape's bucket back to
    the whole descriptor; it does not fail the request.
    """
    limit = non_comma_slot_count(shape)
    kept = {
        fact: index
        for fact, index in assignment.model_dump().items()
        if index is not None and 0 <= index < limit
    }
    return SlotAssignment(**kept)


def infer_slot_map(
    descriptions: list[str], embedded_facts: list[str], client: genai.Client
) -> dict[str, SlotAssignment]:
    """Ask the model which slot index holds each embedded fact, per refined shape.

    Cost is O(distinct shapes): NatWest is ~10 shapes for 36 rows. The model sees
    only the shape strings and word-masked sample rows, never a raw description, so
    it cannot return a payee -- only an index into one.
    """
    buckets = refine_with_slots(descriptions)
    shapes = list(buckets)
    if not shapes:
        return {}

    payload = [
        {
            "shape": shape,
            "samples": [
                mask_words(descriptions[index]) for index, _ in buckets[shape][:3]
            ],
        }
        for shape in shapes
    ]
    prompt = (
        "You are given the structural shapes of a composite bank-descriptor "
        "column, with word-masked sample rows. Do not return any transaction "
        "text; answer only with slot indices, as JSON.\n\n"
        "A shape is a sequence of slot tokens:\n"
        "- W+   a run of one or more words (a payee, a location, a name)\n"
        "- N4   a 4-digit number (N2, N6, ... for other widths; N+ if longer)\n"
        "- DATE a date\n"
        "- PFX  a structural bank prefix or a recurring trailing code\n"
        "- X    punctuation or junk\n"
        "- ,    a comma: a separator, NOT a slot\n\n"
        "Number the slots left to right from 0, skipping commas, so "
        '"N4 DATE W+ , W+ , W+" has slots 0=N4, 1=DATE, 2=W+, 3=W+, 4=W+.\n\n'
        f"For each shape, give the slot index of each of these facts: "
        f"{', '.join(embedded_facts)}. Use null when the shape does not carry the "
        "fact. The payee is the merchant, person or organisation; it is usually "
        "the longest word run. A short word run beside it is often a location and "
        "is not the payee. In the masked samples every word is X, but the numbers "
        "and dates are real and mark where the structural slots sit.\n\n"
        "Return one assignment per shape, in the order given. The shapes are:\n\n"
    )
    interaction = client.interactions.create(
        model="gemini-flash-lite-latest",
        input=prompt + json.dumps(payload, indent=2),
        response_format={
            "type": "text",
            "mime_type": "application/json",
            "schema": _required_everywhere(SlotMap.model_json_schema()),
        },
    )

    if not interaction.output_text:
        raise HTTPException(502, "Model returned no output")

    slot_map = SlotMap.model_validate_json(interaction.output_text)
    if len(slot_map.assignments) != len(shapes):
        raise HTTPException(
            502,
            f"Model returned {len(slot_map.assignments)} slot assignments for "
            f"{len(shapes)} shapes",
        )
    return {
        shape: _validated_assignment(assignment, shape)
        for shape, assignment in zip(shapes, slot_map.assignments)
    }


# Layer-B slot facts mapped to the `Transaction` attribute each one fills. `payee`
# narrows the description; `date` has no attribute (the date always comes from an
# `exact` column) so it is inferred and validated but not applied.
SLOT_FACT_ATTRS = {
    "payee": "description",
    "reference": "reference",
    "txn_type": "txn_type",
}


def apply_slots(
    rows: list[Transaction],
    descriptions: list[str],
    slot_map: dict[str, SlotAssignment],
) -> None:
    """Fill each row from its refined-shape slots, in place.

    `descriptions` is the list `slot_map` was inferred from, so re-bucketing it
    here reproduces the same shapes and slot cuts. A bucket with no assignment, or
    an assignment whose slot for a fact is null, leaves that fact alone -- for the
    payee that means the whole descriptor stays, the pre-layer-B behaviour.
    """
    for shape, members in refine_with_slots(descriptions).items():
        assignment = slot_map.get(shape)
        if assignment is None:
            continue
        for fact, attr in SLOT_FACT_ATTRS.items():
            slot = getattr(assignment, fact)
            if slot is None:
                continue
            for index, row_slots in members:
                setattr(rows[index], attr, row_slots[slot].strip())


# Preset spending categories a bank's own labels are mapped onto, set to set. No
# "Other" on purpose: a label that fits none of these maps to null, which the next
# milestone routes to payee-based categorisation. `CATEGORY_LIST_VERSION` is bumped
# whenever the list changes, because `resolve_category_map` caches on
# (bank category set, this version) -- a user-defined list later reuses that key shape.
CATEGORY_PRESETS = (
    "Groceries",
    "Eating out",
    "Transport",
    "Shopping",
    "Bills",
    "Entertainment",
    "Health",
    "Housing",
    "Savings",
    "Income",
    "Transfers",
    "Fees & charges",
)
CATEGORY_LIST_VERSION = "1"


class CategoryLink(BaseModel):
    """One bank category string and the preset it maps to, or null for no match."""

    source: str = Field(description="A bank category string, copied verbatim.")
    target: str | None = Field(
        None,
        description=(
            "The preset category this bank label best matches, or null when none of "
            "them fit. The bank's label is a strong hint, not binding."
        ),
    )


class CategoryMap(BaseModel):
    """The model's answer: one link per distinct bank category, in any order."""

    links: list[CategoryLink] = Field(default_factory=list)


def _preset_target_schema(model: type[BaseModel], def_name: str) -> dict[str, Any]:
    """`model`'s schema, every property required and its link `target` a preset enum.

    Constraining `target` on the wire is a guard in front of the code-side check in
    the caller: the model picks from the closed preset list rather than free-typing
    a category it could get subtly wrong. The null branch is kept so "no preset
    fits" stays expressible. Shared by the bank-label map and the payee map, which
    differ only in their link definition's name.
    """
    schema = _required_everywhere(model.model_json_schema())
    schema["$defs"][def_name]["properties"]["target"]["anyOf"] = [
        {"type": "string", "enum": list(CATEGORY_PRESETS)},
        {"type": "null"},
    ]
    return schema


def category_map_schema() -> dict[str, Any]:
    return _preset_target_schema(CategoryMap, "CategoryLink")


def infer_category_map(
    bank_categories: list[str], client: genai.Client
) -> dict[str, str | None]:
    """Map a bank's own category labels onto `CATEGORY_PRESETS`, set to set.

    One call for the whole distinct set (Monzo and Starling each ship ~10), never
    per transaction: the model sees only the label strings and the presets, so a
    wrong answer is a mislabelled bucket, not a corrupted row. A target outside the
    preset list is dropped to null here as well as constrained on the wire.
    """
    prompt = (
        "You are given a bank's own spending-category labels and a fixed list of "
        "preset categories. Map each bank label to the preset it best matches, as "
        'JSON. The bank\'s label is a strong hint but not binding: "Transfers" may '
        'still belong under "Housing". Use null when no preset fits. Never use a '
        "category outside the preset list.\n\n"
        f"Preset categories: {', '.join(CATEGORY_PRESETS)}\n\n"
        f"Bank labels: {json.dumps(sorted(bank_categories))}\n"
    )
    interaction = client.interactions.create(
        model="gemini-flash-lite-latest",
        input=prompt,
        response_format={
            "type": "text",
            "mime_type": "application/json",
            "schema": category_map_schema(),
        },
    )

    if not interaction.output_text:
        raise HTTPException(502, "Model returned no output")

    category_map = CategoryMap.model_validate_json(interaction.output_text)
    allowed = set(CATEGORY_PRESETS)
    return {
        link.source: link.target if link.target in allowed else None
        for link in category_map.links
    }


# Memoises `infer_category_map` on (which labels, which preset list). Module-level
# so a re-import of the same bank's statements in a later request skips the call.
_CATEGORY_MAP_CACHE: dict[tuple[frozenset[str], str], dict[str, str | None]] = {}


def resolve_category_map(
    bank_categories: set[str], client: genai.Client
) -> dict[str, str | None]:
    """`infer_category_map`, cached on the category set and the list version.

    The mapping is a property of the label set and the preset list, not of the
    rows, so an unchanged pair asks the model nothing. `CATEGORY_LIST_VERSION` in
    the key means a future user-defined preset list invalidates it cleanly.
    """
    key = (frozenset(bank_categories), CATEGORY_LIST_VERSION)
    if key not in _CATEGORY_MAP_CACHE:
        _CATEGORY_MAP_CACHE[key] = infer_category_map(sorted(bank_categories), client)
    return _CATEGORY_MAP_CACHE[key]


class PayeeLink(BaseModel):
    """One payee string and the preset it maps to, or null for no match."""

    source: str = Field(description="A payee string, copied verbatim.")
    target: str | None = Field(
        None,
        description=(
            "The preset category this payee best fits, or null when none of them "
            "fit or the payee is too generic to place."
        ),
    )


class PayeeCategoryMap(BaseModel):
    """The model's answer: one link per distinct payee, in any order."""

    links: list[PayeeLink] = Field(default_factory=list)


def payee_category_schema() -> dict[str, Any]:
    return _preset_target_schema(PayeeCategoryMap, "PayeeLink")


def infer_payee_categories(
    payees: list[str], client: genai.Client
) -> dict[str, str | None]:
    """Map distinct transaction payees onto `CATEGORY_PRESETS`, set to set.

    The fallback for rows a bank category column did not cover (or covered with a
    label that fit no preset). One call for the whole distinct set, never per
    transaction: the model sees only the payee strings and the presets, so a wrong
    answer is a mislabelled bucket, not a corrupted row. A target outside the
    preset list is dropped to null here as well as constrained on the wire.
    """
    prompt = (
        "You are given a list of transaction payees -- merchants, people and "
        "organisations -- and a fixed list of preset spending categories. Assign "
        "each payee the preset it best fits, as JSON. Use null when no preset fits "
        "or the payee is too generic to place. Never use a category outside the "
        "preset list.\n\n"
        f"Preset categories: {', '.join(CATEGORY_PRESETS)}\n\n"
        f"Payees: {json.dumps(sorted(payees))}\n"
    )
    interaction = client.interactions.create(
        model="gemini-flash-lite-latest",
        input=prompt,
        response_format={
            "type": "text",
            "mime_type": "application/json",
            "schema": payee_category_schema(),
        },
    )

    if not interaction.output_text:
        raise HTTPException(502, "Model returned no output")

    payee_map = PayeeCategoryMap.model_validate_json(interaction.output_text)
    allowed = set(CATEGORY_PRESETS)
    return {
        link.source: link.target if link.target in allowed else None
        for link in payee_map.links
    }


# Memoises payee -> preset one payee at a time, keyed on the preset list version.
# Per-payee rather than per-set (unlike `_CATEGORY_MAP_CACHE`) so two imports --
# from different users -- share every merchant they have in common.
_PAYEE_CATEGORY_CACHE: dict[tuple[str, str], str | None] = {}


def resolve_payee_categories(
    payees: set[str], client: genai.Client
) -> dict[str, str | None]:
    """`infer_payee_categories` for only the payees not already cached.

    A payee the model omits from its answer is cached as None, so it is not
    re-queried on the next import; `CATEGORY_LIST_VERSION` in the key invalidates
    the cache cleanly when the preset list changes.
    """
    version = CATEGORY_LIST_VERSION
    missing = sorted(p for p in payees if (p, version) not in _PAYEE_CATEGORY_CACHE)
    if missing:
        fresh = infer_payee_categories(missing, client)
        for payee in missing:
            _PAYEE_CATEGORY_CACHE[(payee, version)] = fresh.get(payee)
    return {p: _PAYEE_CATEGORY_CACHE[(p, version)] for p in payees}


class CategoryMapEntry(BaseModel):
    """One source label and the preset it maps to, with its provenance.

    `kind` distinguishes a bank category column mapped set-to-set (``"bank"``)
    from the payee fallback (``"payee"``), so the frontend can show and edit both
    as one table while knowing which rows each entry governs. Kept apart from
    `CategoryLink` / `PayeeLink`, which are the model's request schema.
    """

    source: str
    target: str | None
    kind: Literal["bank", "payee"]


class ParseResult(BaseModel):
    """The endpoint's response: the rows plus the mapping their categories derive from."""

    transactions: list[Transaction]
    category_map: list[CategoryMapEntry]


@app.post("/transactions")
def csv_to_transactions(file: UploadFile) -> ParseResult:
    text, _ = decode_csv(file.file.read())

    dialect = detect_dialect(text)
    client = get_client()
    column_mapping = infer_column_mapping(text, client, dialect)

    rows = parse_transactions(text, column_mapping)

    payee = column_mapping.fields.payee
    if payee.purity == "embedded" and payee.column is not None:
        descriptions = [row.description for row in rows]
        slot_map = infer_slot_map(
            descriptions,
            embedded_facts_in(column_mapping.fields, payee.column),
            client,
        )
        apply_slots(rows, descriptions, slot_map)

    # The mapping objects the rows' categories derive from, returned alongside the
    # rows so the frontend can inspect and edit them rather than re-deriving.
    bank_entries: list[CategoryMapEntry] = []
    payee_entries: list[CategoryMapEntry] = []

    # When the bank ships its own category column, map that label set onto the
    # presets in one call rather than categorising any row. A null target (no
    # preset fits, or the model omitted the label) leaves `category` None for the
    # payee-based fallback below.
    if column_mapping.fields.category.purity == "exact":
        bank_categories = {row.category for row in rows if row.category is not None}
        if bank_categories:
            category_map = resolve_category_map(bank_categories, client)
            for row in rows:
                if row.category is not None:
                    row.category_source = row.category
                    row.category = category_map.get(row.category)
            # One entry per distinct label, including any the model omitted
            # (target None), so the mapping table stays complete and editable.
            bank_entries = [
                CategoryMapEntry(source=s, target=category_map.get(s), kind="bank")
                for s in sorted(bank_categories)
            ]

    # Rows still uncategorised -- no bank category column, or a bank label that fit
    # no preset -- fall back to their payee. One call for the distinct payee set,
    # each payee cached across imports and users.
    uncategorised = {row.description for row in rows if row.category is None}
    if uncategorised:
        payee_map = resolve_payee_categories(uncategorised, client)
        for row in rows:
            if row.category is None:
                row.category_source = row.description
                row.category = payee_map.get(row.description)
        payee_entries = [
            CategoryMapEntry(source=s, target=t, kind="payee")
            for s, t in sorted(payee_map.items())
        ]

    return ParseResult(transactions=rows, category_map=[*bank_entries, *payee_entries])
