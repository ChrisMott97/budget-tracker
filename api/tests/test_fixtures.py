"""Expected column mappings for the synthetic bank CSVs in `sample-data/`.

The eval-set half of ROADMAP milestone 5: these pin the *parser* against every
fixture format, with no network and no model. Whether the model infers these
mappings correctly is a separate, still-to-build eval.
"""

import datetime
from pathlib import Path

import pytest

from budget_buddy.main import ColumnMapping, Transaction, decode_csv, parse_transactions

SAMPLE_DATA = Path(__file__).parents[2] / "sample-data"


def transaction(date: str, description: str, amount: float) -> Transaction:
    return Transaction(
        date=datetime.date.fromisoformat(date), description=description, amount=amount
    )


FIXTURES = {
    "amex.csv": (
        ColumnMapping(
            date_column="Date",
            date_format="%d/%m/%Y",
            description_column="Description",
            amount_column="Amount",
        ),
        23,
        transaction("2026-09-07", "TESCO EXPRESS 3411 3411 LONDON", 31.62),
        transaction("2026-08-25", "SPOTIFY                 LONDON", 14.49),
    ),
    "hsbc.csv": (
        ColumnMapping(
            has_header=False,
            date_column="0",
            date_format="%d/%m/%Y",
            description_column="1",
            amount_column="2",
        ),
        25,
        transaction("2026-07-30", "CR BRIGHTFORD LTD SALARY", 3980.44),
        transaction("2026-08-28", "DD PUREGYM LTD", -28.99),
    ),
    "monzo.csv": (
        ColumnMapping(
            date_column="Date",
            date_format="%d/%m/%Y",
            description_column="Name",
            amount_column="Amount",
        ),
        15,
        transaction("2026-09-07", "Tesco", -31.62),
        transaction("2026-08-25", "Spotify", -14.49),
    ),
    "natwest.csv": (
        ColumnMapping(
            date_column="Date",
            date_format="%d %b %Y",
            description_column="Description",
            amount_column="Value",
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
            date_column="Date",
            date_format="%d/%m/%Y",
            description_column="Counter Party",
            amount_column="Amount (GBP)",
        ),
        20,
        transaction("2026-07-30", "Brightford Ltd", 3980.44),
        transaction("2026-08-28", "Puregym Ltd", -28.99),
    ),
}


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
