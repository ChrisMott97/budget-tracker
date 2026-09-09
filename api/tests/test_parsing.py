"""Tests for the pure parsing and anonymisation functions in budget_buddy.main.

These run with no network and no API key.
"""

import datetime

import pytest
from fastapi import HTTPException

from budget_buddy.main import ColumnMapping, decode_csv, parse_transactions, shape


def test_decode_csv_strips_utf8_bom():
    text, encoding = decode_csv("﻿Date,Amount\n".encode())
    assert encoding == "utf-8-sig"
    assert text.startswith("Date")


def test_decode_csv_falls_back_to_cp1252():
    text, encoding = decode_csv("CAF\xc9 NERO".encode("cp1252"))
    assert encoding == "cp1252"
    assert text == "CAFÉ NERO"


def test_shape_collapses_word_runs_and_classifies_numbers():
    assert shape("TESCO STORES 1234 LONDON") == "W+ N4 W+"


def test_shape_keeps_dates_and_commas_as_structure():
    assert shape("AMAZON.CO.UK, 12MAR25, REF 123456789") == "W+ , DATE , W+ N+"


def test_shape_swallows_ampersand_inside_a_name():
    assert shape("MARKS & SPENCER") == "W+"
    assert shape("M&S SIMPLY FOOD") == "W+"


def test_shape_never_leaks_the_original_text():
    description = "DIRECT DEBIT ACME INSURANCE 987654 REF A1B2C3"
    result = shape(description)
    for token in description.split():
        assert token not in result


def test_parse_transactions_maps_columns_and_types():
    csv_text = (
        "Date,Description,Amount\n"
        "2025-03-12,TESCO STORES,-12.50\n"
        "2025-03-13,SALARY,2000.00\n"
    )
    mapping = ColumnMapping(
        date_column="Date", description_column="Description", amount_column="Amount"
    )

    rows = parse_transactions(csv_text, mapping)

    assert [row.amount for row in rows] == [-12.5, 2000.0]
    assert rows[0].date == datetime.date(2025, 3, 12)
    assert rows[0].description == "TESCO STORES"


def test_parse_transactions_honours_skip_rows_and_delimiter():
    csv_text = "Statement for account 1234\nDate;Desc;Amt\n12/03/2025;COFFEE;-3,20\n"
    mapping = ColumnMapping(
        skip_rows=1,
        delimiter=";",
        date_column="Date",
        date_format="%d/%m/%Y",
        description_column="Desc",
        amount_column="Amt",
        amount_separator=",",
    )

    rows = parse_transactions(csv_text, mapping)

    assert len(rows) == 1
    assert rows[0].amount == -3.2
    assert rows[0].date == datetime.date(2025, 3, 12)


HEADERLESS_CSV = (
    '30/07/2026,"CR BRIGHTFORD LTD SALARY          ",3980.44\n'
    '30/07/2026,"DD VODAFONE LTD                   ",-24.50\n'
    '31/07/2026,"))) PRET A MANGER 0641 LONDON     ",-9.45\n'
)


def headerless_mapping(**overrides) -> ColumnMapping:
    return ColumnMapping(
        has_header=False,
        date_column="0",
        date_format="%d/%m/%Y",
        description_column="1",
        amount_column="2",
        **overrides,
    )


def test_parse_transactions_reads_a_headerless_csv_by_position():
    rows = parse_transactions(HEADERLESS_CSV, headerless_mapping())

    assert len(rows) == 3
    assert rows[0].date == datetime.date(2026, 7, 30)
    assert rows[0].description == "CR BRIGHTFORD LTD SALARY"
    assert rows[0].amount == 3980.44


def test_parse_transactions_keeps_the_first_row_when_there_is_no_header():
    """The silent data-loss regression: a name-based mapping eats row one as a header."""
    promoted = parse_transactions(
        HEADERLESS_CSV,
        ColumnMapping(
            date_column="30/07/2026",
            date_format="%d/%m/%Y",
            description_column="CR BRIGHTFORD LTD SALARY          ",
            amount_column="3980.44",
        ),
    )
    assert len(promoted) == 2

    assert len(parse_transactions(HEADERLESS_CSV, headerless_mapping())) == 3


def test_parse_transactions_rejects_named_columns_on_a_headerless_csv():
    mapping = headerless_mapping()
    mapping.date_column = "Date"

    with pytest.raises(HTTPException) as raised:
        parse_transactions(HEADERLESS_CSV, mapping)

    assert raised.value.status_code == 422


def test_parse_transactions_strips_padded_descriptions():
    rows = parse_transactions(HEADERLESS_CSV, headerless_mapping())

    assert [row.description for row in rows] == [
        "CR BRIGHTFORD LTD SALARY",
        "DD VODAFONE LTD",
        "))) PRET A MANGER 0641 LONDON",
    ]
