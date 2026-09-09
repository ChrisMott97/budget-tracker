"""Expected column mappings for the synthetic bank CSVs in `sample-data/`.

The eval-set half of ROADMAP milestone 5: these pin the *parser* against every
fixture format, with no network and no model. Whether the model infers these
mappings correctly is a separate, still-to-build eval.
"""

import datetime
from pathlib import Path

import pytest

from budget_buddy.dialect import Dialect, detect_dialect
from budget_buddy.main import (
    ColumnMapping,
    FieldMap,
    FieldSource,
    Transaction,
    decode_csv,
    parse_transactions,
)

SAMPLE_DATA = Path(__file__).parents[2] / "sample-data"


def transaction(date: str, description: str, amount: float) -> Transaction:
    return Transaction(
        date=datetime.date.fromisoformat(date), description=description, amount=amount
    )


def exact(column: str) -> FieldSource:
    return FieldSource(column=column, purity="exact")


def embedded(column: str) -> FieldSource:
    return FieldSource(column=column, purity="embedded")


FIXTURES = {
    "amex.csv": (
        ColumnMapping(
            date_format="%d/%m/%Y",
            fields=FieldMap(
                date=exact("Date"),
                amount=exact("Amount"),
                payee=embedded("Description"),
            ),
        ),
        23,
        transaction("2026-09-07", "TESCO EXPRESS 3411 3411 LONDON", 31.62),
        transaction("2026-08-25", "SPOTIFY                 LONDON", 14.49),
    ),
    "hsbc.csv": (
        ColumnMapping(
            has_header=False,
            date_format="%d/%m/%Y",
            fields=FieldMap(
                date=exact("0"),
                amount=exact("2"),
                # Column 1 carries both facts, which is what `embedded` is for:
                # "CR BRIGHTFORD LTD SALARY" is a type prefix, a payee and a reference.
                payee=embedded("1"),
                txn_type=embedded("1"),
                reference=embedded("1"),
            ),
        ),
        25,
        transaction("2026-07-30", "CR BRIGHTFORD LTD SALARY", 3980.44),
        transaction("2026-08-28", "DD PUREGYM LTD", -28.99),
    ),
    "monzo.csv": (
        ColumnMapping(
            date_format="%d/%m/%Y",
            fields=FieldMap(
                date=exact("Date"),
                amount=exact("Amount"),
                payee=exact("Name"),
                category=exact("Category"),
                txn_type=exact("Type"),
                currency=exact("Currency"),
                notes=exact("Notes and #tags"),
            ),
        ),
        15,
        transaction("2026-09-07", "Tesco", -31.62),
        transaction("2026-08-25", "Spotify", -14.49),
    ),
    "natwest.csv": (
        ColumnMapping(
            date_format="%d %b %Y",
            fields=FieldMap(
                date=exact("Date"),
                amount=exact("Value"),
                balance=exact("Balance"),
                txn_type=exact("Type"),
                payee=embedded("Description"),
                reference=embedded("Description"),
            ),
        ),
        36,
        transaction("2026-08-28", "PUREGYM LTD", -28.99),
        transaction(
            "2026-07-30",
            "BRIGHTFORD LTD , SALARY , FP 30/07/26 0803 , REV735916042881350",
            3980.44,
        ),
    ),
    "starling.csv": (
        ColumnMapping(
            date_format="%d/%m/%Y",
            fields=FieldMap(
                date=exact("Date"),
                amount=exact("Amount (GBP)"),
                balance=exact("Balance (GBP)"),
                payee=exact("Counter Party"),
                reference=exact("Reference"),
                category=exact("Spending Category"),
                txn_type=exact("Type"),
                notes=exact("Notes"),
            ),
        ),
        20,
        transaction("2026-07-30", "Brightford Ltd", 3980.44),
        transaction("2026-08-28", "Puregym Ltd", -28.99),
    ),
}

# The layer-A answers worth stating outright, because they are the cases that made a
# flat "which column is the payee" unanswerable. Kept separate from FIXTURES so the
# facts the parser never reads are asserted rather than merely present.
EXPECTED_FIELD_SOURCES = [
    ("monzo.csv", "payee", "Name", "exact"),
    ("natwest.csv", "payee", "Description", "embedded"),
    ("amex.csv", "category", None, "absent"),
    ("amex.csv", "balance", None, "absent"),
    ("hsbc.csv", "txn_type", "1", "embedded"),
    ("starling.csv", "category", "Spending Category", "exact"),
]


@pytest.mark.parametrize("name,fact,column,purity", EXPECTED_FIELD_SOURCES)
def test_expected_field_map_answers_the_facts_layer_a_exists_for(
    name: str, fact: str, column: str | None, purity: str
):
    source = getattr(FIXTURES[name][0].fields, fact)

    assert (source.column, source.purity) == (column, purity)


@pytest.mark.parametrize("name", FIXTURES)
def test_sample_csv_parses_with_its_expected_mapping(name: str):
    mapping, expected_rows, first, last = FIXTURES[name]
    text, _ = decode_csv((SAMPLE_DATA / name).read_bytes())

    rows = parse_transactions(text, mapping)

    assert len(rows) == expected_rows
    assert rows[0] == first
    assert rows[-1] == last


@pytest.mark.parametrize("name", FIXTURES)
def test_sample_csv_loses_no_rows(name: str):
    """Guards the failure mode that hid a transaction in hsbc.csv: quiet row loss."""
    mapping, _, _, _ = FIXTURES[name]
    text, _ = decode_csv((SAMPLE_DATA / name).read_bytes())

    rows = parse_transactions(text, mapping)

    data_lines = len([line for line in text.splitlines() if line.strip()])
    assert len(rows) == data_lines - mapping.skip_rows - int(mapping.has_header)


@pytest.mark.parametrize("name", FIXTURES)
def test_detected_dialect_matches_the_expected_mapping(name: str):
    """The sample set doubles as the eval for dialect detection, at no extra cost.

    These three facts used to be inferred by the model alongside the field map; they
    are now measured, so the fixtures pin the measurement against the same answers.
    """
    mapping, _, _, _ = FIXTURES[name]
    text, _ = decode_csv((SAMPLE_DATA / name).read_bytes())

    detected = detect_dialect(text)

    assert detected == Dialect(
        skip_rows=mapping.skip_rows,
        delimiter=mapping.delimiter,
        has_header=mapping.has_header,
    )
